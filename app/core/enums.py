"""
Shared Enums for the Spectra Platform.

Centralizes enum definitions to avoid duplication and ensure consistency.
Follows the DRY (Don't Repeat Yourself) principle.
"""

from app.utils.compat import StrEnum


class AssessmentPhase(StrEnum):
    """
    Phases of a security assessment.

    Used by:
    - Mission Controller for planning
    - Tool Selector for phase-specific tool selection
    - Mission status tracking
    """

    SCOPE = "scope"
    DISCOVERY = "discovery"
    ENUMERATION = "enumeration"
    VULNERABILITY = "vulnerability"
    EXPLOITATION = "exploitation"
    POST_EXPLOITATION = "post_exploitation"
    REPORTING = "reporting"
    COMPLETE = "complete"


class EntityStatus(StrEnum):
    """
    Generic status values for entities in the pipeline.

    Used as base for Target and Mission status enums.
    """

    PENDING = "pending"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    EXPLOITING = "exploiting"
    COMPLETED = "completed"
    FAILED = "failed"


class MissionStatus(StrEnum):
    """Status of a mission in the execution pipeline."""

    CREATED = "created"
    INITIALIZING = "initializing"
    SCOPING = "scoping"
    PLANNING = "planning"
    RUNNING = "running"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    EXECUTING = "executing"
    EXPLOITING = "exploiting"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPING = "stopping"
    PAUSED = "paused"


class Severity(StrEnum):
    """
    CVSS-based severity levels for vulnerabilities.

    Consistent across findings, reports, and AI agent outputs.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RiskLevel(StrEnum):
    """
    Risk level for actions and operations.

    Used by:
    - Agent actions
    - Tool risk assessment
    - Consensus voting thresholds
    """

    PASSIVE = "passive"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
