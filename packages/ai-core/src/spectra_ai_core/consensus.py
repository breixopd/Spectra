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

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from spectra_ai_core.agents.base import ActionRisk, AgentAction
from spectra_ai_core.llm import LLMClient
from spectra_ai_core.prompts import BLUE_TEAM_VOTER_PROMPT, RED_TEAM_VOTER_PROMPT, SAFETY_VALIDATOR_PROMPT

if TYPE_CHECKING:
    from spectra_persistence.models.mission import Mission

logger = logging.getLogger(__name__)


# --- Enums ---


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
    OUTPUT_PARSING = "output_parsing"  # MAKER: vote on parsed facts from tool output
    TOOL_PICK = "tool_pick"  # MAKER: vote on which tool to use next
    RED_FLAG = "red_flag"  # MAKER: red-flag outputs with format/structure errors


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


class ToolSuggestionResponse(BaseModel):
    """Schema for a single voter's next-tool suggestion (MAKER TOOL_PICK gate)."""

    tool: str = Field(..., description="The single best tool to run next, chosen ONLY from the provided list")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence that this is the right next tool")
    reasoning: str = Field("", description="Brief justification for the choice")


class ExtractedFact(BaseModel):
    """A single structured fact extracted from raw tool output (MAKER OUTPUT_PARSING gate)."""

    type: str = Field(..., description="Fact category: service, port, vuln, host, credential, info, etc.")
    name: str = Field(..., description="Short identifier (e.g. '443/tcp', 'CVE-2021-1234', 'admin')")
    value: str = Field("", description="The observed value/version/detail for this fact")
    detail: str = Field("", description="Optional extra context")


class ParsedFactsResponse(BaseModel):
    """A single voter's extraction of structured facts from tool output."""

    facts: list[ExtractedFact] = Field(default_factory=list, description="Facts grounded ONLY in the given output")


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
            ActionRisk.LOW.value: (0, 0, 0.0),  # Skip consensus
            ActionRisk.MEDIUM.value: (3, 2, 0.5),  # 2 of 3, moderate confidence
            ActionRisk.HIGH.value: (3, 3, 0.7),  # 3 of 3, high confidence
            ActionRisk.CRITICAL.value: (3, 3, 0.8),  # 3 of 3, strict confidence
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
        mission: Mission | None = None,
    ):
        self.llm = llm
        self.config = config or VotingConfig()
        self.mission = mission

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

        # Skip voting for low-risk actions
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
                escalation_reason=f"Action at {gate.value} gate requires human approval",
            )

        # Conduct voting with gate-specific parameters
        votes = await self._collect_votes_with_params(action, context, num_voters)

        # Analyze votes with gate-specific thresholds
        return self._analyze_votes_with_params(votes, action, k_threshold, min_confidence)

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
        """Check if an action requires consensus voting.

        Uses risk-aware consensus_threshold: LOW risk skips voting entirely.
        """
        risk = action.risk_level
        risk_str = risk.value if hasattr(risk, "value") else str(risk)
        threshold_entry = self.config.consensus_threshold.get(risk_str)
        if threshold_entry is not None:
            num_voters, _k, _conf = threshold_entry
            if num_voters == 0:
                return False

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

        Uses ``REQUIRE_APPROVAL`` env kill-switch; otherwise the per-mission
        ``requires_approval`` flag when the mission is fully autonomous.
        """
        from spectra_common.config import settings

        risk_levels = [
            ActionRisk.LOW,
            ActionRisk.MEDIUM,
            ActionRisk.HIGH,
            ActionRisk.CRITICAL,
        ]
        action_idx = risk_levels.index(action.risk_level)
        threshold_idx = risk_levels.index(self.config.human_approval_risk)
        if settings.REQUIRE_APPROVAL:
            return action_idx >= threshold_idx
        if self.mission and getattr(self.mission, "requires_approval", None) is not None and not self.mission.requires_approval:
            return False  # Mission is fully autonomous
        return action_idx >= threshold_idx

    async def _collect_votes(
        self,
        action: AgentAction,
        context: dict[str, Any] | None,
    ) -> list[Vote]:
        """Collect votes from multiple LLM instances."""
        return await self._collect_votes_with_params(action, context, self.config.num_voters)

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
        tasks = [self._get_vote(action, context, f"voter_{i}", temp) for i, temp in enumerate(temperatures)]

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
        system_prompt: str | None = None,
    ) -> Vote:
        """Get a vote from a single LLM instance."""
        prompt = self._build_voting_prompt(action, context)
        effective_prompt = system_prompt or SAFETY_VALIDATOR_PROMPT

        try:
            response = await self.llm.generate_structured(
                prompt=prompt,
                response_model=VoteResponse,
                system_prompt=effective_prompt,
                temperature=temperature,
            )

            return Vote(
                voter_id=voter_id,
                decision=response.decision,
                confidence=response.confidence,
                reasoning=response.reasoning,
                concerns=response.concerns,
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
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
            context_str = "\n\nContext:\n" + "\n".join(f"- {k}: {v}" for k, v in context.items())

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
        return self._analyze_votes_with_params(votes, action, self.config.k_threshold, self.config.min_confidence)

    def _analyze_votes_with_params(
        self,
        votes: list[Vote],
        action: AgentAction,
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
        avg_confidence = sum(v.confidence for v in approve_votes) / len(approve_votes) if approve_votes else 0.0

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
                escalation_reason = (
                    f"Approval votes met but confidence too low ({avg_confidence:.2f} < {min_confidence})"
                )
        elif reject_count > len(votes) // 2:
            status = ConsensusStatus.REJECTED
            # Collect rejection reasons
            rejection_reasons = [v.reasoning for v in votes if v.decision == VoteDecision.REJECT]
            escalation_reason = "; ".join(rejection_reasons[:3])
        else:
            status = ConsensusStatus.NO_CONSENSUS
            escalation_reason = (
                f"No clear majority (approve: {approve_count}, reject: {reject_count}, abstain: {abstain_count})"
            )

        # NO_CONSENSUS escalation: handle based on action risk level
        if status == ConsensusStatus.NO_CONSENSUS:
            risk = action.risk_level
            risk_str = risk.value if hasattr(risk, "value") else str(risk)
            logger.warning(
                "NO_CONSENSUS for %s (risk=%s): approve=%d reject=%d abstain=%d conf=%.2f — %s",
                action.action_type,
                risk_str,
                approve_count,
                reject_count,
                abstain_count,
                avg_confidence,
                escalation_reason,
            )
            if risk_str == ActionRisk.CRITICAL.value:
                # Critical actions with no consensus must be reviewed by a human
                status = ConsensusStatus.PENDING_HUMAN
                escalation_reason = (
                    f"CRITICAL action with no consensus — flagged for human review ({escalation_reason})"
                )
            elif approve_count > reject_count:
                # Lower-risk: fall back to majority vote even if below k-threshold
                status = ConsensusStatus.APPROVED
                final_decision = True
                escalation_reason = (
                    f"No consensus but majority approved ({approve_count}/{len(votes)}) "
                    f"at {risk_str} risk — proceeding with majority"
                )
                logger.warning("Falling back to majority approval: %s", escalation_reason)

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

    async def debate_exploit(
        self,
        action: AgentAction,
        context: dict[str, Any] | None = None,
        *,
        num_rounds: int = 2,
    ) -> ConsensusResult:
        """Red-team/blue-team debate for exploit decisions.

        Gets perspectives from both attacker and defender viewpoints
        to validate the exploit approach before execution.
        """
        attacker_system = RED_TEAM_VOTER_PROMPT
        defender_system = BLUE_TEAM_VOTER_PROMPT

        perspectives = [
            ("attacker", attacker_system, 0.3),
            ("defender", defender_system, 0.3),
        ]

        votes: list[Vote] = []
        for _round in range(num_rounds):
            for voter_id, role_system_prompt, temperature in perspectives:
                vote = await self._get_vote(action, context, voter_id, temperature, system_prompt=role_system_prompt)
                votes.append(vote)

        return self._analyze_votes_with_params(votes, action, k_threshold=len(votes), min_confidence=0.6)

    # ── MAKER: Subtask-level voting ───────────────────────────────────

    async def vote_on_tool_selection(
        self,
        available_tools: list[str],
        phase: str,
        target_info: dict[str, Any],
        num_voters: int = 3,
    ) -> dict[str, Any]:
        """Multiple micro-agents independently suggest the next tool (MAKER TOOL_PICK gate).

        Each voter is an independent LLM call (parallel, temperature-varied) that picks
        the next tool from ``available_tools``. Returns the majority pick, or the
        highest-confidence suggestion when there is no majority. Falls back to the
        first available tool only if every voter fails.
        """
        from collections import Counter

        if not available_tools:
            return {"tool": "", "confidence": 0.0, "votes": 0, "total_voters": 0}
        if num_voters < 2 or len(available_tools) == 1:
            return {"tool": available_tools[0], "confidence": 0.6, "votes": 1, "total_voters": 1}

        temp_min, temp_max = self.config.temperature_range
        temp_step = (temp_max - temp_min) / max(num_voters - 1, 1)
        prompt = self._build_tool_pick_prompt(available_tools, phase, target_info)
        tasks = [self._suggest_tool(prompt, available_tools, temp_min + i * temp_step) for i in range(num_voters)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        suggestions: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, dict) and result.get("tool"):
                suggestions.append(result)
            elif isinstance(result, Exception):
                logger.warning("Tool-pick voter %d failed: %s", i, result)

        if not suggestions:
            # Every voter failed — degrade gracefully rather than randomly guessing.
            return {"tool": available_tools[0], "confidence": 0.5, "votes": 0, "total_voters": num_voters, "note": "voter_failure"}

        tool_votes = Counter(s["tool"] for s in suggestions)
        winner, count = tool_votes.most_common(1)[0]

        if count >= len(suggestions) // 2 + 1:  # Majority of successful voters
            avg_conf = sum(s["confidence"] for s in suggestions if s["tool"] == winner) / count
            return {"tool": winner, "confidence": round(avg_conf, 2), "votes": count, "total_voters": len(suggestions)}

        # No majority — pick highest confidence
        best = max(suggestions, key=lambda s: s["confidence"])
        return {
            "tool": best["tool"],
            "confidence": round(best["confidence"], 2),
            "votes": 1,
            "total_voters": len(suggestions),
            "note": "no_majority",
        }

    def _build_tool_pick_prompt(
        self,
        available_tools: list[str],
        phase: str,
        target_info: dict[str, Any],
    ) -> str:
        """Build the prompt asking a voter to pick the next tool."""
        tools_str = "\n".join(f"- {t}" for t in available_tools)
        target_str = "\n".join(f"- {k}: {v}" for k, v in (target_info or {}).items())
        return f"""You are selecting the single most useful tool to run NEXT in an authorized
penetration test, given the current phase and what is known about the target.

Current phase: {phase}

Target information:
{target_str or "- (none yet)"}

Available tools (choose EXACTLY ONE, by its exact name from this list):
{tools_str}

Pick the tool that best advances the mission in this phase. Return the exact tool
name, a confidence between 0 and 1, and a one-sentence justification.
"""

    async def _suggest_tool(
        self,
        prompt: str,
        available_tools: list[str],
        temperature: float,
    ) -> dict[str, Any] | None:
        """Get a single voter's tool suggestion via an independent LLM call."""
        response = await self.llm.generate_structured(
            prompt=prompt,
            response_model=ToolSuggestionResponse,
            system_prompt="You are an expert offensive-security operator choosing the next tool.",
            temperature=temperature,
        )
        tool = response.tool.strip()
        if tool not in available_tools:
            # Tolerate minor formatting drift (case / surrounding text) before discarding.
            match = next((t for t in available_tools if t.lower() == tool.lower()), None)
            if match is None:
                match = next((t for t in available_tools if t.lower() in tool.lower()), None)
            if match is None:
                logger.debug("Tool-pick voter returned out-of-list tool %r; discarding", tool)
                return None
            tool = match
        return {"tool": tool, "confidence": float(response.confidence)}

    async def vote_on_output_parsing(
        self,
        output: str,
        extraction_hint: str = "",
        num_voters: int = 2,
        max_chars: int = 16000,
    ) -> dict[str, Any]:
        """Extract structured facts from raw tool output via consensus (MAKER OUTPUT_PARSING gate).

        Multiple voters independently extract facts; only facts agreed on by at least a
        majority of successful voters are kept, which suppresses single-model
        hallucinations on free-form output. Returns ``{facts, voters, agreed}`` where
        each fact carries an ``agreement`` count and a ``source`` marker.
        """
        text = (output or "").strip()
        if not text:
            return {"facts": [], "voters": 0, "agreed": 0}
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated for parsing]"

        num_voters = max(num_voters, 1)
        temp_min, temp_max = self.config.temperature_range
        temp_step = (temp_max - temp_min) / max(num_voters - 1, 1)
        prompt = self._build_output_parsing_prompt(text, extraction_hint)
        tasks = [self._extract_facts(prompt, temp_min + i * temp_step) for i in range(num_voters)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ballots: list[list[dict[str, str]]] = []
        for i, result in enumerate(results):
            if isinstance(result, list):
                ballots.append(result)
            elif isinstance(result, Exception):
                logger.warning("Output-parsing voter %d failed: %s", i, result)

        if not ballots:
            return {"facts": [], "voters": num_voters, "agreed": 0, "note": "voter_failure"}

        # Reconcile: a fact is kept when a majority of successful voters report it.
        from collections import Counter

        def _key(fact: dict[str, str]) -> str:
            return f"{fact.get('type', '').strip().lower()}|{fact.get('name', '').strip().lower()}"

        counts: Counter[str] = Counter()
        representative: dict[str, dict[str, str]] = {}
        for ballot in ballots:
            for fact in {_key(f): f for f in ballot}.values():  # dedupe within a single voter
                counts[_key(fact)] += 1
                representative.setdefault(_key(fact), fact)

        threshold = len(ballots) // 2 + 1 if len(ballots) > 1 else 1
        agreed_facts: list[dict[str, Any]] = []
        for key, count in counts.items():
            if count >= threshold:
                fact: dict[str, Any] = dict(representative[key])
                fact["agreement"] = count
                fact["source"] = "consensus_parsing"
                agreed_facts.append(fact)

        return {"facts": agreed_facts, "voters": len(ballots), "agreed": len(agreed_facts)}

    def _build_output_parsing_prompt(self, output: str, extraction_hint: str) -> str:
        """Build the prompt asking a voter to extract structured facts from tool output."""
        hint = f"\nFocus on extracting: {extraction_hint}\n" if extraction_hint else ""
        return f"""Extract structured, factual observations from the following security-tool output.
Report ONLY facts that are explicitly present in the output. Do NOT infer, guess, or
add anything not directly supported by the text. If nothing concrete is present, return
an empty list.{hint}
For each fact provide: type (service|port|vuln|host|credential|info), a short name, the
observed value, and optional detail.

--- TOOL OUTPUT START ---
{output}
--- TOOL OUTPUT END ---
"""

    async def _extract_facts(self, prompt: str, temperature: float) -> list[dict[str, str]]:
        """Get a single voter's fact extraction via an independent LLM call."""
        response = await self.llm.generate_structured(
            prompt=prompt,
            response_model=ParsedFactsResponse,
            system_prompt="You are a precise security-output parser. Extract only grounded facts.",
            temperature=temperature,
        )
        return [f.model_dump() for f in response.facts]

    def red_flag_check(self, output: str, expected_format: str = "structured") -> dict[str, Any]:
        """Check tool output for red flags (MAKER RED_FLAG gate).

        Red flags indicate the output may be corrupted, incomplete, or formatted
        incorrectly. These outputs are discarded rather than patched.

        Returns:
            Dict with 'flagged' bool, 'reason' str, and 'severity' (error/warn)
        """
        flags: list[dict[str, str]] = []

        # Empty output
        if not output or not output.strip():
            flags.append({"type": "empty_output", "reason": "Tool produced no output", "severity": "error"})

        # Truncated output indicators
        if output.strip().endswith("...") or "[TRUNCATED]" in output:
            flags.append({"type": "truncated", "reason": "Output appears truncated", "severity": "error"})

        # JSON format expected but not valid
        if expected_format == "json":
            try:
                import json as _json
                _json.loads(output)
            except Exception:
                flags.append({"type": "invalid_json", "reason": "Expected JSON but output is not valid JSON", "severity": "error"})

        # XML format expected but not valid
        if expected_format == "xml":
            import re
            if not re.search(r"<\?xml|<[a-zA-Z]+>", output):
                flags.append({"type": "invalid_xml", "reason": "Expected XML but no XML tags found", "severity": "error"})

        # Error indicators in output
        error_keywords = ["segmentation fault", "core dumped", "killed", "out of memory", "connection refused"]
        output_lower = output.lower()
        for kw in error_keywords:
            if kw in output_lower:
                flags.append({"type": "error_indicator", "reason": f"Output contains error: '{kw}'", "severity": "warn"})
                break

        if flags:
            errors = [f for f in flags if f["severity"] == "error"]
            if errors:
                return {"flagged": True, "reason": errors[0]["reason"], "severity": "error", "flags": flags}
            return {"flagged": True, "reason": flags[0]["reason"], "severity": "warn", "flags": flags}

        return {"flagged": False, "reason": "", "severity": "none", "flags": flags}
