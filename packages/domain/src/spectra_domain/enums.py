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
    TIMED_OUT = "timed_out"
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


class MissionMilestone(StrEnum):
    """
    M1-M11 pentest milestones from CheckMate paper.

    Tracks meaningful progress from enumeration through post-exploitation.
    """

    M1_TARGET_ENUMERATION = "m1_target_enumeration"
    M2_VECTOR_IDENTIFICATION = "m2_vector_identification"
    M3_INITIAL_ACCESS = "m3_initial_access"
    M4_CREDENTIAL_ACCESS = "m4_credential_access"
    M5_PRIVILEGE_ESCALATION = "m5_privilege_escalation"
    M6_LOCAL_RECON = "m6_local_recon"
    M7_LATERAL_MOVEMENT = "m7_lateral_movement"
    M8_DATA_COLLECTION = "m8_data_collection"
    M9_DATA_EXFILTRATION = "m9_data_exfiltration"
    M10_PERSISTENCE = "m10_persistence"
    M11_COVERAGE_COMPLETE = "m11_coverage_complete"

    @property
    def label(self) -> str:
        """Human-readable label for the milestone."""
        labels = {
            MissionMilestone.M1_TARGET_ENUMERATION: "Target Enumeration",
            MissionMilestone.M2_VECTOR_IDENTIFICATION: "Vector Confirmed",
            MissionMilestone.M3_INITIAL_ACCESS: "Initial Access (Shell)",
            MissionMilestone.M4_CREDENTIAL_ACCESS: "Credential Access",
            MissionMilestone.M5_PRIVILEGE_ESCALATION: "Privilege Escalation",
            MissionMilestone.M6_LOCAL_RECON: "Local Reconnaissance",
            MissionMilestone.M7_LATERAL_MOVEMENT: "Lateral Movement",
            MissionMilestone.M8_DATA_COLLECTION: "Data Collection",
            MissionMilestone.M9_DATA_EXFILTRATION: "Data Exfiltration",
            MissionMilestone.M10_PERSISTENCE: "Persistence",
            MissionMilestone.M11_COVERAGE_COMPLETE: "Coverage Complete",
        }
        return labels.get(self, self.value)


class MissionMilestoneStatus(StrEnum):
    """Status of a mission milestone."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
