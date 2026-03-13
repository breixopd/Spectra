"""Seed default subscription plans into the database."""

from __future__ import annotations

import logging

logger = logging.getLogger("spectra.billing")


async def seed_default_plans() -> None:
    """Create default plans if none exist."""
    try:
        from sqlalchemy import func, select

        from app.core.database import async_session_maker
        from app.models.plan import Plan

        async with async_session_maker() as session:
            result = await session.execute(select(func.count(Plan.id)))
            count = result.scalar() or 0
            if count > 0:
                return

            default_plans = [
                Plan(
                    name="free",
                    display_name="Free",
                    description="Get started with basic manual security testing",
                    is_default=True,
                    sort_order=0,
                    max_concurrent_missions=1,
                    max_missions_per_month=5,
                    max_targets=10,
                    sandbox_max_containers=1,
                    sandbox_resource_tier="small",
                    max_storage_mb=100,
                    max_api_requests_per_hour=50,
                    max_api_requests_per_day=200,
                    features={
                        "autonomous_mode": False,
                        "manual_mode": True,
                        "report_export": ["json"],
                        "custom_wordlists": False,
                        "pipeline_builder": False,
                        "cve_browser": True,
                        "shell_access": False,
                        "api_access": False,
                        "vpn_support": False,
                        "advanced_reporting": False,
                        "byok": False,
                    },
                ),
                Plan(
                    name="starter",
                    display_name="Starter",
                    description="For individual security researchers and bug bounty hunters",
                    is_default=False,
                    sort_order=1,
                    max_concurrent_missions=2,
                    max_missions_per_month=25,
                    max_targets=50,
                    sandbox_max_containers=1,
                    sandbox_resource_tier="medium",
                    max_storage_mb=500,
                    max_api_requests_per_hour=100,
                    max_api_requests_per_day=1000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": False,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": False,
                        "vpn_support": False,
                        "advanced_reporting": False,
                        "byok": False,
                    },
                ),
                Plan(
                    name="professional",
                    display_name="Professional",
                    description="Full-featured assessments for professional pentesters and consultancies",
                    is_default=False,
                    sort_order=2,
                    max_concurrent_missions=5,
                    max_missions_per_month=None,
                    max_targets=500,
                    sandbox_max_containers=3,
                    sandbox_resource_tier="large",
                    max_storage_mb=5000,
                    max_api_requests_per_hour=500,
                    max_api_requests_per_day=5000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": True,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": True,
                        "vpn_support": True,
                        "advanced_reporting": True,
                        "byok": False,
                    },
                ),
                Plan(
                    name="enterprise",
                    display_name="Enterprise",
                    description="Full platform access with BYOK, dedicated support, custom SLA, and unlimited everything",
                    is_default=False,
                    sort_order=3,
                    max_concurrent_missions=999,
                    max_missions_per_month=None,
                    max_targets=None,
                    sandbox_max_containers=10,
                    sandbox_resource_tier="xlarge",
                    max_storage_mb=50000,
                    max_api_requests_per_hour=5000,
                    max_api_requests_per_day=50000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": True,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": True,
                        "vpn_support": True,
                        "advanced_reporting": True,
                        "team_sharing": True,
                        "byok": True,
                    },
                ),
            ]
            session.add_all(default_plans)
            await session.commit()
            logger.info("Created %d default plans", len(default_plans))
    except Exception as e:
        logger.warning("Failed to seed default plans: %s", e)
