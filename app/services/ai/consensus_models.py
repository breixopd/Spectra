"""Data models for the Consensus Engine - Voting System."""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from app.services.ai.agents.models import ActionRisk


class VoteDecision(StrEnum):
    """Possible vote decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"
    NEEDS_INFO = "needs_info"


class ConsensusStatus(StrEnum):
    """Status of consensus attempt."""

    APPROVED = "approved"  # K-threshold met
    REJECTED = "rejected"  # Majority rejected
    NO_CONSENSUS = "no_consensus"  # No clear majority
    PENDING_HUMAN = "pending_human"  # Escalated to human


class QualityGate(StrEnum):
    """
    Quality gates where validation occurs.

    Different gates have different validation strictness
    to balance thoroughness with performance.
    """

    PLAN = "plan"  # Initial mission planning - thorough
    TOOL_SELECTION = "tool"  # Tool selection - quick validation
    PAYLOAD = "payload"  # Exploit/payload crafting - thorough
    REPLAN = "replan"  # Replanning after errors - thorough
    EXECUTION = "execution"  # High-risk execution - strictest


class Vote(BaseModel):
    """A single vote from an LLM instance."""

    voter_id: str = Field(..., description="Identifier for the voting instance")
    decision: VoteDecision = Field(..., description="The vote decision")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in decision")
    reasoning: str = Field(..., description="Explanation for the vote")
    concerns: list[str] = Field(default_factory=list, description="Any concerns raised")


class VoteResponse(BaseModel):
    """Schema for LLM vote response (excludes voter_id)."""

    decision: VoteDecision
    confidence: float
    reasoning: str
    concerns: list[str] = []


class ConsensusResult(BaseModel):
    """Result of a consensus vote."""

    status: ConsensusStatus
    votes: list[Vote]
    approve_count: int = 0
    reject_count: int = 0
    abstain_count: int = 0
    average_confidence: float = 0.0
    final_decision: bool = False
    escalation_reason: str | None = None


@dataclass
class VotingConfig:
    """Configuration for the voting system."""

    # Number of voters (LLM instances) to use
    num_voters: int = 3

    # K-threshold: minimum votes needed to approve (K out of N)
    k_threshold: int = 2

    # Minimum average confidence to accept vote
    min_confidence: float = 0.6

    # Temperature variation for diverse opinions
    temperature_range: tuple[float, float] = (0.3, 0.7)

    # Actions at or above this risk level require voting
    voting_risk_threshold: ActionRisk = ActionRisk.HIGH

    # Actions at this risk level always require human approval
    human_approval_risk: ActionRisk = ActionRisk.CRITICAL

    # Risk-aware consensus thresholds
    # LOW risk → skip consensus entirely
    # MEDIUM risk → require 2/3 agreement
    # HIGH+ risk → full 3/3 consensus
    consensus_threshold: dict[str, tuple[int, int, float]] = field(
        default_factory=lambda: {
            ActionRisk.LOW.value: (0, 0, 0.0),       # Skip consensus
            ActionRisk.MEDIUM.value: (3, 2, 0.5),     # 2 of 3, moderate confidence
            ActionRisk.HIGH.value: (3, 3, 0.7),       # 3 of 3, high confidence
            ActionRisk.CRITICAL.value: (3, 3, 0.8),   # 3 of 3, strict confidence
        }
    )

    # Quality gate specific configurations
    # Maps gate -> (num_voters, k_threshold, min_confidence)
    gate_configs: dict[str, tuple[int, int, float]] = field(
        default_factory=lambda: {
            QualityGate.PLAN.value: (
                3,
                2,
                0.7,
            ),  # Thorough: 3 voters, need 2, high confidence
            QualityGate.TOOL_SELECTION.value: (
                2,
                2,
                0.5,
            ),  # Quick: 2 voters, need both, moderate
            QualityGate.PAYLOAD.value: (
                3,
                2,
                0.7,
            ),  # Thorough: 3 voters, need 2, high confidence
            QualityGate.REPLAN.value: (3, 2, 0.6),  # Moderate: 3 voters, need 2
            QualityGate.EXECUTION.value: (3, 3, 0.8),  # Strictest: 3 voters, need all 3
        }
    )
