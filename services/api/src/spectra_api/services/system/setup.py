"""System Setup Service: Handles initialization of admin user and infrastructure configuration."""

import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.exceptions import SpectraError
from app.auth.security import get_password_hash
from app.core.config import settings
from app.models.user import User
from app.services.system.runtime_settings import (
    hydrate_runtime_settings_from_db,
    upsert_system_config_values,
)
from spectra_api.api.schemas.system import SystemSetupRequest
from spectra_common.paths import data_path

logger = logging.getLogger(__name__)


class SystemSetupService:
    """Service to handle initial system setup and configuration."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def perform_setup(self, setup_in: SystemSetupRequest) -> User:
        """
        Orchestrate the entire setup process.

        1. Create Admin User
        2. Configure AI/LLM
        3. Configure Infrastructure (DB)
        4. Re-initialize services
        """
        try:
            # 1. Create User
            user = await self._create_admin_user(setup_in)

            # 2. Configure System Configs (DB, LLM)
            await self._configure_system(setup_in)

            # 3. Handle Infrastructure persistence (JSON) & Docker
            await self._handle_infrastructure_changes(setup_in)

            # 4. Apply custom AI model config if provided
            if setup_in.ai_models:
                await self._apply_custom_ai_config(setup_in.ai_models)

            # Commit changes
            await self.session.commit()
            await self.session.refresh(user)

            await hydrate_runtime_settings_from_db(
                self.session,
                persist_normalized=True,
                commit=True,
            )

            return user

        except (OSError, RuntimeError, ValueError) as e:
            await self.session.rollback()
            logger.error("Setup failed: %s", e, exc_info=True)
            raise SpectraError(
                "Setup failed due to an internal error.",
                code="SETUP_FAILED",
            ) from e

    async def _create_admin_user(self, setup_in: SystemSetupRequest) -> User:
        """Create the initial superuser."""
        user = User(
            username=setup_in.user.username,
            email=setup_in.user.email,
            hashed_password=get_password_hash(setup_in.user.password),
            is_active=True,
            is_superuser=True,
        )
        self.session.add(user)
        return user

    async def _configure_system(self, setup_in: SystemSetupRequest) -> None:
        """Create or update SystemConfig entries in the database."""
        config_values: dict[str, tuple[str, bool]] = {}

        # TensorZero gateway
        if setup_in.tensorzero_gateway_url:
            config_values["TENSORZERO_GATEWAY_URL"] = (setup_in.tensorzero_gateway_url, False)
        if setup_in.tensorzero_api_key:
            config_values["TENSORZERO_API_KEY"] = (setup_in.tensorzero_api_key, True)

        # Embedding configuration
        if setup_in.embedding_model:
            config_values["EMBEDDING_MODEL"] = (setup_in.embedding_model, False)

        # Database Configs (Stored in DB for reference, even if used via JSON)
        if setup_in.use_custom_db and setup_in.database_url:
            config_values["DATABASE_URL"] = (setup_in.database_url, True)

        # Service topology settings
        service_topology_fields: dict[str, tuple[str | None, bool]] = {
            "SANDBOX_ORCHESTRATOR_URL": (setup_in.sandbox_orchestrator_url, False),
            "SANDBOX_ORCHESTRATOR_API_KEY": (setup_in.sandbox_orchestrator_api_key, True),
        }
        for key, (value, is_secret) in service_topology_fields.items():
            if value:
                config_values[key] = (value, is_secret)

        await upsert_system_config_values(self.session, config_values)

        # Persist setup metadata
        setup_meta: dict[str, tuple[str, bool]] = {}
        if setup_in.allow_registration is not None:
            setup_meta["ALLOW_REGISTRATION"] = (str(setup_in.allow_registration).lower(), False)
        if setup_in.platform_base_url:
            setup_meta["PLATFORM_BASE_URL"] = (setup_in.platform_base_url, False)
        if setup_in.app_name:
            setup_meta["APP_NAME"] = (setup_in.app_name, False)
        if setup_in.contact_email:
            setup_meta["CONTACT_EMAIL"] = (setup_in.contact_email, False)
        if setup_meta:
            await upsert_system_config_values(self.session, setup_meta)

    async def _handle_infrastructure_changes(self, setup_in: SystemSetupRequest) -> None:
        """Handle infrastructure changes: save config and manage containers."""
        infra_updates = {}

        if setup_in.use_custom_db and setup_in.database_url:
            infra_updates["DATABASE_URL"] = setup_in.database_url

        if infra_updates:
            self._save_infra_config(infra_updates)

    async def _apply_custom_ai_config(self, ai_models: dict) -> None:
        """Write custom model config to tensorzero.toml during setup."""
        import tomllib

        config_path = Path(__file__).resolve().parents[2] / "config" / "tensorzero.toml"
        if not config_path.exists():
            config_path = Path("/app/config/tensorzero.toml")
        if not config_path.exists():
            logger.warning("Cannot find tensorzero.toml to apply custom AI config")
            return

        with open(config_path, "rb") as f:
            current = tomllib.load(f)

        provider_type = ai_models.get("provider_type", "openai")
        tiers: dict[str, dict[str, str]] = {}
        for tier in ("fast", "balanced", "capable"):
            tier_conf = ai_models.get(tier, {})
            tiers[tier] = {
                "primary": tier_conf.get("primary", ""),
                "fallback": tier_conf.get("fallback", ""),
            }

        lines = [
            "# TensorZero Gateway Configuration for Spectra",
            "# Configured during initial setup",
            "",
            "[gateway]",
            'bind_address = "0.0.0.0:3000"',
            "",
            "# --- Models ---",
        ]

        for tier_name, models in tiers.items():
            primary = models["primary"]
            fallback = models["fallback"]
            if fallback:
                lines += [
                    f"[models.{tier_name}]",
                    'routing = ["primary", "fallback"]',
                    "",
                    f"[models.{tier_name}.providers.primary]",
                    f'type = "{provider_type}"',
                    f'model_name = "{primary}"',
                    "",
                    f"[models.{tier_name}.providers.fallback]",
                    f'type = "{provider_type}"',
                    f'model_name = "{fallback}"',
                    "",
                ]
            else:
                lines += [
                    f"[models.{tier_name}]",
                    'routing = ["primary"]',
                    "",
                    f"[models.{tier_name}.providers.primary]",
                    f'type = "{provider_type}"',
                    f'model_name = "{primary}"',
                    "",
                ]

        lines.append("# --- Functions ---")
        for fname, fconf in current.get("functions", {}).items():
            ftype = fconf.get("type", "chat")
            lines += [f"[functions.{fname}]", f'type = "{ftype}"', ""]
            for vname, vconf in fconf.get("variants", {}).items():
                vtype = vconf.get("type", "chat_completion")
                vmodel = vconf.get("model", "balanced")
                lines += [
                    f"[functions.{fname}.variants.{vname}]",
                    f'type = "{vtype}"',
                    f'model = "{vmodel}"',
                    "",
                ]

        lines.append("# --- Metrics ---")
        for mname, mconf in current.get("metrics", {}).items():
            mtype = mconf.get("type", "boolean")
            mlevel = mconf.get("level", "inference")
            mopt = mconf.get("optimize", "max")
            lines += [
                f"[metrics.{mname}]",
                f'type = "{mtype}"',
                f'level = "{mlevel}"',
                f'optimize = "{mopt}"',
                "",
            ]

        config_path.write_text("\n".join(lines) + "\n")
        logger.info("Custom AI model configuration applied to tensorzero.toml")

    def _save_infra_config(self, updates: dict) -> None:
        """Save infrastructure config to persistent file."""
        config_path = data_path("config", "infra_config.json")
        data = {}

        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError, KeyError) as e:
                logger.warning("Could not read existing infra config: %s", e)

        data.update(updates)

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (OSError, ValueError, KeyError) as e:
            logger.error("Failed to save infra config: %s", e)

    async def _reinitialize_llm(self, setup_in: SystemSetupRequest) -> None:
        """Re-initialize the global LLM client with TensorZero settings."""
        import spectra_ai.llm as llm_module
        from spectra_ai.llm import close_global_llm_client

        await close_global_llm_client()

        try:
            from spectra_ai.llm import get_llm_client

            new_client = get_llm_client(
                gateway_url=setup_in.tensorzero_gateway_url or settings.TENSORZERO_GATEWAY_URL,
            )

            llm_module._global_llm_client = new_client
            logger.info("LLM client reinitialized with TensorZero gateway")
        except (OSError, RuntimeError, ImportError) as e:
            logger.error("Failed to initialize LLM client: %s", e)
            # Don't fail the whole setup if LLM fails, user can fix later

    async def check_database(self) -> bool:
        """Check database connectivity."""
        try:
            # Use 1 instead of "1" for cross-db compatibility (Postgres/SQLite)
            await self.session.execute(text("SELECT 1"))
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Database check failed: %s", e)
            return False

    async def check_docker(self) -> bool:
        """Check Docker connectivity and version."""
        try:
            import asyncio

            # Use subprocess to check docker version
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.debug("Docker version: %s", stdout.decode().strip())
                return True
            logger.error("Docker check failed: %s", stderr.decode())
            return False
        except (OSError, RuntimeError, ImportError) as e:
            logger.error("Docker check failed: %s", e)
            return False

    async def _stop_container(self, container_name_suffix: str) -> None:
        """Try to stop a container by name suffix (e.g. 'db' matches 'spectra-db')."""
        try:
            import asyncio

            # Get list of running containers
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--format", "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if stdout:
                for name in stdout.decode().splitlines():
                    name = name.strip()
                    if name and (
                        name.endswith(container_name_suffix) or name.strip("/").endswith(container_name_suffix)
                    ):
                        logger.info("Stopping container: %s", name)
                        await asyncio.create_subprocess_exec("docker", "stop", name)
                        break
        except (OSError, RuntimeError, ImportError) as e:
            logger.warning("Failed to stop container *%s: %s", container_name_suffix, e)

    async def check_directories(self) -> bool:
        """Check required directories exist and are writable."""
        required_dirs = [
            "reports",
            "logs",
            "keys",
        ]
        try:
            for d in required_dirs:
                path = Path(d)
                path.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    logger.error("Directory missing: %s", d)
                    return False
            return True
        except (OSError, ValueError, KeyError) as e:
            logger.error("Directory check failed: %s", e)
            return False

    async def verify_system(self) -> dict:
        """Run all system checks and return status report."""
        checks = {
            "database": await self.check_database(),
            "docker": await self.check_docker(),
            "directories": await self.check_directories(),
        }

        # Determine overall status
        status = "healthy" if all(checks.values()) else "unhealthy"

        return {"status": status, **checks}
