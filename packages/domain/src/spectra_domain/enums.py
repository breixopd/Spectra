"""Shared domain enums."""

from enum import StrEnum


class RiskLevel(StrEnum):
    """
    Risk level for actions and operations.

    Used by agent actions, tool risk assessment, and consensus voting thresholds.
    """

    PASSIVE = "passive"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
