"""
Rules of Engagement Validator.

Provides validation functions to check if actions and targets
are compliant with the mission's Rules of Engagement constraints.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spectra_platform.models.roe import RulesOfEngagement

logger = logging.getLogger(__name__)


class RoeValidator:
    """Validator for Rules of Engagement constraints."""

    @staticmethod
    def is_target_authorized(roe: RulesOfEngagement, target_address: str) -> bool:
        """
        Check if a target IP/hostname is within authorized targets.

        Returns True if:
        - authorized_targets is empty (all targets allowed)
        - target matches any entry in authorized_targets
        - target is NOT in excluded_targets
        """
        if not roe:
            return True

        authorized = roe.authorized_targets or []
        excluded = roe.excluded_targets or []

        if not authorized:
            return target_address not in excluded

        target_normalized = target_address.strip().lower()

        for excl in excluded:
            if RoeValidator._matches_target(target_normalized, excl):
                return False

        for auth in authorized:
            if RoeValidator._matches_target(target_normalized, auth):
                return True

        return False

    @staticmethod
    def is_action_allowed(roe: RulesOfEngagement, action: str) -> bool:
        """
        Check if an action is in authorized_actions and not in prohibited_actions.

        Returns True if:
        - authorized_actions is empty (all actions allowed)
        - action is in authorized_actions
        - action is NOT in prohibited_actions
        """
        if not roe:
            return True

        authorized = roe.authorized_actions or []
        prohibited = roe.prohibited_actions or []

        action_normalized = action.strip().lower()

        if prohibited and action_normalized in [a.strip().lower() for a in prohibited]:
            return False

        if not authorized:
            return True

        return action_normalized in [a.strip().lower() for a in authorized]

    @staticmethod
    def check_exfiltration(roe: RulesOfEngagement, bytes_count: int) -> bool:
        """
        Check if data exfiltration is allowed and within limits.

        Returns True if:
        - data_exfiltration_allowed is True
        - bytes_count is within max_exfiltration_bytes (if set)
        """
        if not roe:
            return True

        if not roe.data_exfiltration_allowed:
            return False

        max_bytes = roe.max_exfiltration_bytes
        if max_bytes is not None and bytes_count > max_bytes:
            return False

        return True

    @staticmethod
    def validate_action(
        roe: RulesOfEngagement | None,
        target: str,
        action: str,
        details: str = "",
    ) -> tuple[bool, str]:
        """
        Full validation returning (allowed, reason).

        Checks:
        - Target authorization
        - Action allowed
        - Scan intensity compatibility

        Returns (True, "") if allowed, (False, reason) if blocked.
        """
        if not roe:
            return True, ""

        if not RoeValidator.is_target_authorized(roe, target):
            return False, f"Target '{target}' is not authorized by RoE constraints"

        if not RoeValidator.is_action_allowed(roe, action):
            return False, f"Action '{action}' is not allowed by RoE constraints"

        return True, ""

    @staticmethod
    def get_scan_intensity(roe: RulesOfEngagement | None) -> str:
        """Get the max scan intensity level from RoE."""
        if not roe:
            return "normal"
        return roe.max_scan_intensity or "normal"

    @staticmethod
    def requires_operator_signoff(roe: RulesOfEngagement | None) -> bool:
        """Check if operator signoff is required for this mission."""
        if not roe:
            return False
        return roe.operator_signoff_required

    @staticmethod
    def _matches_target(target: str, pattern: str) -> bool:
        """
        Check if target matches a pattern (IP, CIDR, or hostname/domain).

        Supports:
        - Exact match
        - CIDR notation (e.g., 10.0.0.0/24)
        - Domain wildcard (e.g., *.example.com)
        - Partial domain match (e.g., example.com matches sub.example.com)
        """
        pattern = pattern.strip().lower()

        if target == pattern:
            return True

        try:
            target_ip = ipaddress.ip_address(target)
            try:
                network = ipaddress.ip_network(pattern, strict=False)
                return target_ip in network
            except ValueError:
                pass
        except ValueError:
            pass

        if pattern.startswith("*."):
            domain_suffix = pattern[2:]
            return target.endswith(domain_suffix)

        if "." in pattern:
            return target.endswith(pattern) or target == pattern

        return False


async def get_mission_roe(mission_id: str) -> RulesOfEngagement | None:
    """Load RoE for a mission from the database."""
    try:
        from sqlalchemy import select
        from spectra_platform.core.database import async_session_maker
        from spectra_platform.models.roe import RulesOfEngagement

        async with async_session_maker() as session:
            result = await session.execute(
                select(RulesOfEngagement).where(
                    RulesOfEngagement.mission_id == mission_id
                )
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.warning("Failed to load RoE for mission %s: %s", mission_id, e)
        return None