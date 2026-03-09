"""System Setup Service: Handles initialization of admin user and infrastructure configuration."""

import json
import logging
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.ai.llm as llm_module
from app.api.schemas import SystemSetupRequest
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User
from app.services.ai.llm import close_global_llm_client, get_llm_client
from app.services.system.runtime_settings import (
    build_runtime_ai_config_from_payload,
    hydrate_runtime_settings_from_db,
    serialize_runtime_ai_config_values,
    upsert_system_config_values,
)

logger = logging.getLogger("spectra.services.system")


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

            # Commit changes
            await self.session.commit()
            await self.session.refresh(user)

            await hydrate_runtime_settings_from_db(
                self.session,
                persist_normalized=True,
                commit=True,
            )

            # 4. Generate Security Keys (for Plugin Signing)
            self._generate_signing_keys()

            return user

        except Exception as e:
            await self.session.rollback()
            logger.error("Setup failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Setup failed due to an internal error.",
            ) from e

    def _generate_signing_keys(self) -> None:
        """Generate Ed25519 keys for plugin signing if they don't exist."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519

            keys_dir = Path("keys")
            keys_dir.mkdir(parents=True, exist_ok=True)

            private_key_path = keys_dir / "plugin_signing.pem"
            public_key_path = keys_dir / "plugin_signing.pub"

            if private_key_path.exists() and public_key_path.exists():
                logger.info("Signing keys already exist")
                return

            logger.info("Generating new Ed25519 signing keys...")
            private_key = ed25519.Ed25519PrivateKey.generate()
            public_key = private_key.public_key()

            # Save Private Key
            with open(private_key_path, "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

            # Save Public Key
            with open(public_key_path, "wb") as f:
                f.write(
                    public_key.public_bytes(
                        encoding=serialization.Encoding.OpenSSH,
                        format=serialization.PublicFormat.OpenSSH,
                    )
                )

            logger.info("Signing keys generated successfully")

        except ImportError:
            logger.error("Cryptography package missing - cannot generate keys")
        except Exception as e:
            logger.error("Failed to generate signing keys: %s", e)

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
        runtime_ai_config = build_runtime_ai_config_from_payload(
            provider_profiles=(
                {
                    name: profile.model_dump(exclude_none=True)
                    for name, profile in setup_in.provider_profiles.items()
                }
                if setup_in.provider_profiles
                else None
            ),
            provider_routing=(
                setup_in.provider_routing.as_dict()
                if setup_in.provider_routing
                else None
            ),
            provider_fallbacks=(
                setup_in.provider_fallbacks.as_dict()
                if setup_in.provider_fallbacks
                else None
            ),
            legacy_provider=setup_in.llm_provider,
            legacy_model=setup_in.llm_model,
            legacy_api_key=setup_in.llm_api_key,
            legacy_api_base_url=setup_in.llm_api_base,
            legacy_ollama_host=setup_in.ollama_host,
            legacy_ollama_model=setup_in.ollama_model,
            legacy_ollama_enabled=(
                setup_in.provider_ollama
                or (setup_in.provider_api and setup_in.provider_ollama)
            ),
            legacy_tier_models={
                "LLM_TIER1_MODEL": setup_in.llm_tier1_model,
                "LLM_TIER2_MODEL": setup_in.llm_tier2_model,
                "LLM_TIER3_MODEL": setup_in.llm_tier3_model,
            },
        )

        config_values = serialize_runtime_ai_config_values(runtime_ai_config)

        # Embedding configuration
        if setup_in.embedding_model:
            config_values["EMBEDDING_MODEL"] = (setup_in.embedding_model, False)
        if setup_in.embedding_provider is not None:
            config_values["EMBEDDING_PROVIDER"] = (setup_in.embedding_provider, False)

        # Automation setting
        config_values["FULLY_AUTOMATED"] = (str(settings.FULLY_AUTOMATED).lower(), False)

        # Database Configs (Stored in DB for reference, even if used via JSON)
        if setup_in.use_custom_db and setup_in.database_url:
            config_values["DATABASE_URL"] = (setup_in.database_url, True)

        await upsert_system_config_values(self.session, config_values)

    async def _handle_infrastructure_changes(
        self, setup_in: SystemSetupRequest
    ) -> None:
        """Handle infrastructure changes: save config and manage containers."""
        infra_updates = {}

        if setup_in.use_custom_db and setup_in.database_url:
            infra_updates["DATABASE_URL"] = setup_in.database_url

        if infra_updates:
            self._save_infra_config(infra_updates)

    def _save_infra_config(self, updates: dict) -> None:
        """Save infrastructure config to persistent file."""
        config_path = Path("reports/infra_config.json")
        data = {}

        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning("Could not read existing infra config: %s", e)

        data.update(updates)

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save infra config: %s", e)

    async def _reinitialize_llm(self, setup_in: SystemSetupRequest) -> None:
        """Re-initialize the global LLM client with new settings."""
        await close_global_llm_client()

        try:
            if setup_in.llm_provider == "ollama":
                new_client = get_llm_client(
                    provider="ollama",
                    host=setup_in.ollama_host or "http://localhost:11434",
                    model=setup_in.llm_model,
                )
            else:
                if not setup_in.llm_api_key:
                    # Should be caught by validation earlier, but safety check
                    return

                new_client = get_llm_client(
                    provider="api",
                    api_key=setup_in.llm_api_key,
                    base_url=setup_in.llm_api_base,
                    model=setup_in.llm_model,
                )

            llm_module._global_llm_client = new_client
            logger.info(
                "LLM client reinitialized with provider: %s", setup_in.llm_provider
            )
        except Exception as e:
            logger.error("Failed to initialize LLM client: %s", e)
            # Don't fail the whole setup if LLM fails, user can fix later

    async def check_database(self) -> bool:
        """Check database connectivity."""
        try:
            # Use 1 instead of "1" for cross-db compatibility (Postgres/SQLite)
            await self.session.execute(text("SELECT 1"))
            return True
        except Exception as e:
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
        except Exception as e:
            logger.error("Docker check failed: %s", e)
            return False

    async def _stop_container(self, container_name_suffix: str) -> None:
        """Try to stop a container by name suffix (e.g. 'db' matches 'spectra-db')."""
        try:
            import asyncio

            # Get list of running containers
            proc = await asyncio.create_subprocess_shell(
                "docker ps --format '{{.Names}}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if stdout:
                for name in stdout.decode().splitlines():
                    name = name.strip()
                    if name and (
                        name.endswith(container_name_suffix)
                        or name.strip("/").endswith(container_name_suffix)
                    ):
                        logger.info("Stopping container: %s", name)
                        await asyncio.create_subprocess_exec("docker", "stop", name)
                        break
        except Exception as e:
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
        except Exception as e:
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
