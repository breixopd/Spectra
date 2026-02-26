"""
Consensus Engine - Voting System for Multi-Agent Decisions.

Implements the K-Threshold voting mechanism for the MAKER framework:
- Multiple agents vote on decisions at various quality gates
- Actions proceed only if confidence threshold is met
- Falls back to human approval when consensus fails

Quality Gates (validation points):
- PLAN: Initial mission planning
- TOOL_SELECTION: Each tool selection decision
- PAYLOAD: Exploit/payload generation
- REPLAN: Any plan changes due to errors or unexpected output
- EXECUTION: High-risk tool execution
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.services.ai.agents.base import ActionRisk, AgentAction
from app.services.ai.llm import LLMClient

logger = logging.getLogger("spectra.ai.consensus")


# --- Enums ---


class VoteDecision(str, Enum):
    """Possible vote decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"
    NEEDS_INFO = "needs_info"


class ConsensusStatus(str, Enum):
    """Status of consensus attempt."""

    APPROVED = "approved"  # K-threshold met
    REJECTED = "rejected"  # Majority rejected
    NO_CONSENSUS = "no_consensus"  # No clear majority
    PENDING_HUMAN = "pending_human"  # Escalated to human


class QualityGate(str, Enum):
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


# --- Models ---


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


# --- Voting System ---


class VotingSystem:
    """
    Implements K-Threshold consensus voting for multi-agent decisions.

    The voting process:
    1. Present the action to N LLM instances
    2. Each instance votes APPROVE/REJECT with confidence
    3. If >= K votes approve AND avg confidence >= threshold: APPROVED
    4. If majority rejects: REJECTED
    5. Otherwise: NO_CONSENSUS (escalate to human)

    Example:
        voting = VotingSystem(llm_client, config)
        result = await voting.vote_on_action(action, context)
        if result.status == ConsensusStatus.APPROVED:
            execute_action(action)
    """

    def __init__(
        self,
        llm: LLMClient,
        config: VotingConfig | None = None,
    ):
        self.llm = llm
        self.config = config or VotingConfig()

    async def validate_at_gate(
        self,
        gate: QualityGate,
        action: AgentAction,
        context: dict[str, Any] | None = None,
    ) -> ConsensusResult:
        """
        Validate an action at a specific quality gate.

        Different gates have different validation parameters optimized
        for their specific use case (speed vs thoroughness).

        Args:
            gate: The quality gate (PLAN, TOOL_SELECTION, etc.)
            action: The action to validate.
            context: Additional context for voters.

        Returns:
            ConsensusResult with the voting outcome.
        """
        # Get gate-specific config
        gate_config = self.config.gate_configs.get(
            gate.value,
            (
                self.config.num_voters,
                self.config.k_threshold,
                self.config.min_confidence,
            ),
        )
        num_voters, k_threshold, min_confidence = gate_config

        # Check if it needs human approval regardless
        if self.requires_human_approval(action):
            return ConsensusResult(
                status=ConsensusStatus.PENDING_HUMAN,
                votes=[],
                escalation_reason=f"Action at {gate.value} gate requires human approval",
            )

        # Conduct voting with gate-specific parameters
        votes = await self._collect_votes_with_params(action, context, num_voters)

        # Analyze votes with gate-specific thresholds
        return self._analyze_votes_with_params(
            votes, action, k_threshold, min_confidence
        )

    async def vote_on_action(
        self,
        action: AgentAction,
        context: dict[str, Any] | None = None,
    ) -> ConsensusResult:
        """
        Conduct a vote on the proposed action.

        Args:
            action: The action to vote on.
            context: Additional context for voters.

        Returns:
            ConsensusResult with the voting outcome.
        """
        # Check if voting is required
        if not self.requires_voting(action):
            return ConsensusResult(
                status=ConsensusStatus.APPROVED,
                votes=[],
                final_decision=True,
            )

        # Check if it needs human approval regardless
        if self.requires_human_approval(action):
            return ConsensusResult(
                status=ConsensusStatus.PENDING_HUMAN,
                votes=[],
                escalation_reason="Action risk level requires human approval",
            )

        # Conduct parallel voting
        votes = await self._collect_votes(action, context)

        # Analyze votes
        return self._analyze_votes(votes, action)

    def requires_voting(self, action: AgentAction) -> bool:
        """Check if an action requires consensus voting."""
        risk_levels = [
            ActionRisk.LOW,
            ActionRisk.MEDIUM,
            ActionRisk.HIGH,
            ActionRisk.CRITICAL,
        ]
        action_idx = risk_levels.index(action.risk_level)
        threshold_idx = risk_levels.index(self.config.voting_risk_threshold)
        return action_idx >= threshold_idx

    def requires_human_approval(self, action: AgentAction) -> bool:
        """Check if an action always requires human approval.

        Returns False if FULLY_AUTOMATED mode is enabled in settings.
        """
        from app.core.config import settings

        # In fully automated mode, never require human approval
        if settings.FULLY_AUTOMATED:
            return False

        risk_levels = [
            ActionRisk.LOW,
            ActionRisk.MEDIUM,
            ActionRisk.HIGH,
            ActionRisk.CRITICAL,
        ]
        action_idx = risk_levels.index(action.risk_level)
        threshold_idx = risk_levels.index(self.config.human_approval_risk)
        return action_idx >= threshold_idx

    async def _collect_votes(
        self,
        action: AgentAction,
        context: dict[str, Any] | None,
    ) -> list[Vote]:
        """Collect votes from multiple LLM instances."""
        return await self._collect_votes_with_params(
            action, context, self.config.num_voters
        )

    async def _collect_votes_with_params(
        self,
        action: AgentAction,
        context: dict[str, Any] | None,
        num_voters: int,
    ) -> list[Vote]:
        """Collect votes from specified number of LLM instances."""
        # Calculate temperature for each voter
        temp_min, temp_max = self.config.temperature_range
        temp_step = (temp_max - temp_min) / max(num_voters - 1, 1)
        temperatures = [temp_min + i * temp_step for i in range(num_voters)]

        # Create voting tasks
        tasks = [
            self._get_vote(action, context, f"voter_{i}", temp)
            for i, temp in enumerate(temperatures)
        ]

        # Run in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failures
        votes = []
        for i, result in enumerate(results):
            if isinstance(result, Vote):
                votes.append(result)
            else:
                logger.warning("Voter %d failed: %s", i, result)

        return votes

    async def _get_vote(
        self,
        action: AgentAction,
        context: dict[str, Any] | None,
        voter_id: str,
        temperature: float,
    ) -> Vote:
        """Get a vote from a single LLM instance."""
        prompt = self._build_voting_prompt(action, context)
        system_prompt = """You are a security assessment validator. Your role is to evaluate proposed actions for safety and appropriateness.

Consider:
1. Is this action safe to execute?
2. Could it cause unintended damage?
3. Is it appropriate for the stated mission?
4. Are there any red flags or concerns?

Vote APPROVE if the action is safe and appropriate.
Vote REJECT if the action is dangerous or inappropriate.
Vote ABSTAIN if you cannot make a determination.
Vote NEEDS_INFO if more context is required."""

        try:
            response = await self.llm.generate_structured(
                prompt=prompt,
                response_model=VoteResponse,
                system_prompt=system_prompt,
                temperature=temperature,
            )

            return Vote(
                voter_id=voter_id,
                decision=response.decision,
                confidence=response.confidence,
                reasoning=response.reasoning,
                concerns=response.concerns,
            )
        except Exception as e:
            logger.error("Vote generation failed for %s: %s", voter_id, e)
            # Return abstain vote on failure
            return Vote(
                voter_id=voter_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning=f"Vote generation failed: {e}",
                concerns=["Voter failed to generate response"],
            )

    def _build_voting_prompt(
        self,
        action: AgentAction,
        context: dict[str, Any] | None,
    ) -> str:
        """Build the prompt for voters."""
        context_str = ""
        if context:
            context_str = "\n\nContext:\n" + "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        return f"""Evaluate this proposed security assessment action.
The user has authorized this assessment against the target.
Standard security tools and exploits are expected and allowed if they advance the mission.

Action Type: {action.action_type}
Risk Level: {action.risk_level}
Reasoning: {action.reasoning}
Confidence: {action.confidence}

Full Action Details:
{action.model_dump_json(indent=2)}
{context_str}

Should this action be approved?
Vote APPROVE if it is a standard security tool/action targeting the authorized host.
Vote REJECT only if it is clearly dangerous (e.g. destructive, out of scope) or completely irrelevant.
"""

    def _analyze_votes(
        self,
        votes: list[Vote],
        action: AgentAction,
    ) -> ConsensusResult:
        """Analyze collected votes and determine consensus."""
        return self._analyze_votes_with_params(
            votes, action, self.config.k_threshold, self.config.min_confidence
        )

    def _analyze_votes_with_params(
        self,
        votes: list[Vote],
        _action: AgentAction,
        k_threshold: int,
        min_confidence: float,
    ) -> ConsensusResult:
        """Analyze collected votes with specified parameters."""
        if not votes:
            return ConsensusResult(
                status=ConsensusStatus.NO_CONSENSUS,
                votes=[],
                escalation_reason="No votes collected",
            )

        # Count votes
        approve_count = sum(1 for v in votes if v.decision == VoteDecision.APPROVE)
        reject_count = sum(1 for v in votes if v.decision == VoteDecision.REJECT)
        abstain_count = sum(1 for v in votes if v.decision == VoteDecision.ABSTAIN)

        # Calculate average confidence of approvals
        approve_votes = [v for v in votes if v.decision == VoteDecision.APPROVE]
        avg_confidence = (
            sum(v.confidence for v in approve_votes) / len(approve_votes)
            if approve_votes
            else 0.0
        )

        # Determine status
        status: ConsensusStatus
        final_decision = False
        escalation_reason = None

        if approve_count >= k_threshold:
            if avg_confidence >= min_confidence:
                status = ConsensusStatus.APPROVED
                final_decision = True
            else:
                status = ConsensusStatus.NO_CONSENSUS
                escalation_reason = f"Approval votes met but confidence too low ({avg_confidence:.2f} < {min_confidence})"
        elif reject_count > len(votes) // 2:
            status = ConsensusStatus.REJECTED
            # Collect rejection reasons
            rejection_reasons = [
                v.reasoning for v in votes if v.decision == VoteDecision.REJECT
            ]
            escalation_reason = "; ".join(rejection_reasons[:3])
        else:
            status = ConsensusStatus.NO_CONSENSUS
            escalation_reason = f"No clear majority (approve: {approve_count}, reject: {reject_count}, abstain: {abstain_count})"

        return ConsensusResult(
            status=status,
            votes=votes,
            approve_count=approve_count,
            reject_count=reject_count,
            abstain_count=abstain_count,
            average_confidence=avg_confidence,
            final_decision=final_decision,
            escalation_reason=escalation_reason,
        )

    async def request_human_approval(
        self,
        action: AgentAction,
        consensus_result: ConsensusResult | None = None,
    ) -> dict[str, Any]:
        """
        Generate a human-readable approval request.

        This should be sent to the user via WebSocket.

        Returns:
            Dict containing approval request details.
        """
        concerns = []
        if consensus_result and consensus_result.votes:
            for vote in consensus_result.votes:
                concerns.extend(vote.concerns)

        return {
            "type": "approval_request",
            "action": action.model_dump(),
            "consensus": consensus_result.model_dump() if consensus_result else None,
            "concerns": list(set(concerns)),  # Deduplicate
            "message": f"Action requires approval: {action.action_type}",
            "timeout_seconds": 300,
        }
