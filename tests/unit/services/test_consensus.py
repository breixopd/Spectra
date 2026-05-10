"""
Tests for the Consensus system and Quality Gates.
"""

import pytest

from spectra_platform.services.ai.agents.base import ActionRisk, AgentAction, ToolAction
from spectra_platform.services.ai.consensus import (
    ConsensusResult,
    ConsensusStatus,
    QualityGate,
    Vote,
    VoteDecision,
    VotingConfig,
    VotingSystem,
)
from tests.mocks.llm import MockLLMClient


class TestQualityGateEnum:
    """Tests for the QualityGate enum."""

    def test_quality_gate_values(self):
        """QualityGate should have all expected values."""
        assert QualityGate.PLAN.value == "plan"
        assert QualityGate.TOOL_SELECTION.value == "tool"
        assert QualityGate.PAYLOAD.value == "payload"
        assert QualityGate.REPLAN.value == "replan"
        assert QualityGate.EXECUTION.value == "execution"

    def test_quality_gates_count(self):
        """Should have 8 quality gates (5 original + 3 MAKER subtask gates)."""
        gates = list(QualityGate)
        assert len(gates) == 8


class TestVotingConfig:
    """Tests for VotingConfig defaults."""

    def test_default_config(self):
        """VotingConfig should have sensible defaults."""
        config = VotingConfig()

        assert config.num_voters == 3
        assert config.k_threshold == 2
        assert config.min_confidence == 0.6
        assert config.voting_risk_threshold == ActionRisk.HIGH
        assert config.human_approval_risk == ActionRisk.CRITICAL

    def test_gate_configs_exist(self):
        """VotingConfig should have gate-specific configs."""
        config = VotingConfig()

        assert "plan" in config.gate_configs
        assert "tool" in config.gate_configs
        assert "payload" in config.gate_configs
        assert "replan" in config.gate_configs
        assert "execution" in config.gate_configs

    def test_gate_config_structure(self):
        """Each gate config should be (num_voters, k_threshold, min_confidence)."""
        config = VotingConfig()

        for _gate, gate_config in config.gate_configs.items():
            assert len(gate_config) == 3
            num_voters, k_threshold, min_confidence = gate_config
            assert isinstance(num_voters, int)
            assert isinstance(k_threshold, int)
            assert isinstance(min_confidence, float)
            assert k_threshold <= num_voters
            assert 0 <= min_confidence <= 1


class TestVotingSystemBasics:
    """Basic tests for VotingSystem."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client."""
        return MockLLMClient(
            structured_responses={
                "VoteResponse": {
                    "decision": "approve",
                    "confidence": 0.8,
                    "reasoning": "Test approval",
                    "concerns": [],
                }
            }
        )

    @pytest.fixture
    def voting_system(self, mock_llm):
        """Create a VotingSystem with mock LLM."""
        return VotingSystem(mock_llm)

    def test_requires_voting_for_high_risk(self, voting_system):
        """High risk actions should require voting."""
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.HIGH,
            reasoning="Test action",
        )

        assert voting_system.requires_voting(action) is True

    def test_does_not_require_voting_for_low_risk(self, voting_system):
        """Low risk actions should not require voting by default."""
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.LOW,
            reasoning="Test action",
        )

        assert voting_system.requires_voting(action) is False

    def test_requires_human_approval_for_critical(self, voting_system):
        """Critical actions should require human approval."""
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Test action",
        )

        assert voting_system.requires_human_approval(action) is True

    def test_does_not_require_human_for_high_risk(self, voting_system):
        """High risk actions should not require human approval."""
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.HIGH,
            reasoning="Test action",
        )

        assert voting_system.requires_human_approval(action) is False


class TestVoteOnAction:
    """Tests for vote_on_action method."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client that returns approve votes."""
        return MockLLMClient(
            structured_responses={
                "VoteResponse": {
                    "decision": "approve",
                    "confidence": 0.85,
                    "reasoning": "Action looks safe",
                    "concerns": [],
                }
            }
        )

    @pytest.mark.asyncio
    async def test_low_risk_auto_approves(self, mock_llm):
        """Low risk actions should auto-approve without voting."""
        voting = VotingSystem(mock_llm)
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.LOW,
            reasoning="Test",
        )

        result = await voting.vote_on_action(action)

        assert result.status == ConsensusStatus.APPROVED
        assert result.final_decision is True
        assert len(result.votes) == 0  # No actual voting occurred

    @pytest.mark.asyncio
    async def test_critical_escalates_to_human(self, mock_llm):
        """Critical actions should escalate to human without voting."""
        voting = VotingSystem(mock_llm)
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Test",
        )

        result = await voting.vote_on_action(action)

        assert result.status == ConsensusStatus.PENDING_HUMAN
        assert result.final_decision is False
        assert len(result.votes) == 0


class TestValidateAtGate:
    """Tests for validate_at_gate method."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client."""
        return MockLLMClient(
            structured_responses={
                "VoteResponse": {
                    "decision": "approve",
                    "confidence": 0.9,
                    "reasoning": "Test approval",
                    "concerns": [],
                }
            }
        )

    @pytest.mark.asyncio
    async def test_validate_at_plan_gate(self, mock_llm):
        """Validation at PLAN gate should work."""
        voting = VotingSystem(mock_llm)
        action = AgentAction(
            action_type="mission_plan",
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Test plan",
        )

        result = await voting.validate_at_gate(QualityGate.PLAN, action, {"target": "192.168.1.1", "task_count": 5})

        # With mock returning approve, should be approved
        assert result.status == ConsensusStatus.APPROVED

    @pytest.mark.asyncio
    async def test_validate_at_tool_gate(self, mock_llm):
        """Validation at TOOL_SELECTION gate should work."""
        voting = VotingSystem(mock_llm)
        action = ToolAction(
            action_type="run_tool",
            confidence=0.8,
            risk_level=ActionRisk.LOW,
            reasoning="Running nmap",
            tool_name="nmap",
            target="192.168.1.1",
            estimated_duration=60,
        )

        result = await voting.validate_at_gate(
            QualityGate.TOOL_SELECTION, action, {"phase": "discovery", "tool": "nmap"}
        )

        assert result.status == ConsensusStatus.APPROVED

    @pytest.mark.asyncio
    async def test_critical_at_any_gate_escalates(self, mock_llm):
        """Critical actions at any gate should escalate to human."""
        voting = VotingSystem(mock_llm)
        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Dangerous action",
        )

        result = await voting.validate_at_gate(QualityGate.PAYLOAD, action, {})

        assert result.status == ConsensusStatus.PENDING_HUMAN


class TestVoteAnalysis:
    """Tests for vote analysis logic."""

    def test_analyze_votes_approves_when_threshold_met(self):
        """Should approve when k-threshold is met with sufficient confidence."""
        config = VotingConfig(k_threshold=2, min_confidence=0.6)
        voting = VotingSystem(MockLLMClient(), config)

        votes = [
            Vote(
                voter_id="v1",
                decision=VoteDecision.APPROVE,
                confidence=0.8,
                reasoning="Good",
            ),
            Vote(
                voter_id="v2",
                decision=VoteDecision.APPROVE,
                confidence=0.7,
                reasoning="Fine",
            ),
            Vote(
                voter_id="v3",
                decision=VoteDecision.REJECT,
                confidence=0.5,
                reasoning="Not sure",
            ),
        ]

        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Test",
        )

        result = voting._analyze_votes(votes, action)

        assert result.status == ConsensusStatus.APPROVED
        assert result.approve_count == 2
        assert result.reject_count == 1
        assert result.final_decision is True

    def test_analyze_votes_rejects_when_majority_rejects(self):
        """Should reject when majority votes reject."""
        config = VotingConfig(k_threshold=2, min_confidence=0.6)
        voting = VotingSystem(MockLLMClient(), config)

        votes = [
            Vote(
                voter_id="v1",
                decision=VoteDecision.REJECT,
                confidence=0.8,
                reasoning="Dangerous",
            ),
            Vote(
                voter_id="v2",
                decision=VoteDecision.REJECT,
                confidence=0.9,
                reasoning="Too risky",
            ),
            Vote(
                voter_id="v3",
                decision=VoteDecision.APPROVE,
                confidence=0.5,
                reasoning="Maybe ok",
            ),
        ]

        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Test",
        )

        result = voting._analyze_votes(votes, action)

        assert result.status == ConsensusStatus.REJECTED
        assert result.reject_count == 2
        assert result.final_decision is False

    def test_analyze_votes_no_consensus_when_split(self):
        """Should fall back to majority approval when approve > reject at MEDIUM risk."""
        config = VotingConfig(k_threshold=2, min_confidence=0.6)
        voting = VotingSystem(MockLLMClient(), config)

        votes = [
            Vote(
                voter_id="v1",
                decision=VoteDecision.APPROVE,
                confidence=0.6,
                reasoning="Ok",
            ),
            Vote(
                voter_id="v2",
                decision=VoteDecision.ABSTAIN,
                confidence=0.3,
                reasoning="Unsure",
            ),
            Vote(
                voter_id="v3",
                decision=VoteDecision.ABSTAIN,
                confidence=0.2,
                reasoning="Not sure",
            ),
        ]

        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Test",
        )

        result = voting._analyze_votes(votes, action)

        # approve(1) > reject(0) at MEDIUM risk → majority fallback → APPROVED
        assert result.status == ConsensusStatus.APPROVED
        assert result.final_decision is True

    def test_analyze_votes_low_confidence_triggers_no_consensus(self):
        """Low confidence with approvals at MEDIUM risk → majority fallback."""
        config = VotingConfig(k_threshold=2, min_confidence=0.8)
        voting = VotingSystem(MockLLMClient(), config)

        votes = [
            Vote(
                voter_id="v1",
                decision=VoteDecision.APPROVE,
                confidence=0.5,
                reasoning="Maybe",
            ),
            Vote(
                voter_id="v2",
                decision=VoteDecision.APPROVE,
                confidence=0.6,
                reasoning="Perhaps",
            ),
        ]

        action = AgentAction(
            action_type="test",
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Test",
        )

        result = voting._analyze_votes(votes, action)

        # approve(2) > reject(0) at MEDIUM risk → majority fallback → APPROVED
        assert result.status == ConsensusStatus.APPROVED
        assert result.final_decision is True
        assert "majority" in (result.escalation_reason or "").lower()


class TestHumanApprovalRequest:
    """Tests for human approval request generation."""

    @pytest.mark.asyncio
    async def test_request_human_approval_format(self):
        """request_human_approval should return proper format."""
        voting = VotingSystem(MockLLMClient())
        action = AgentAction(
            action_type="exploit",
            confidence=0.9,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Attempting RCE exploit",
        )

        request = await voting.request_human_approval(action)

        assert request["type"] == "approval_request"
        assert "action" in request
        assert "timeout_seconds" in request
        assert request["timeout_seconds"] == 300

    @pytest.mark.asyncio
    async def test_request_includes_concerns_from_votes(self):
        """request_human_approval should include concerns from votes."""
        voting = VotingSystem(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.5,
            risk_level=ActionRisk.HIGH,
            reasoning="Test",
        )

        consensus_result = ConsensusResult(
            status=ConsensusStatus.NO_CONSENSUS,
            votes=[
                Vote(
                    voter_id="v1",
                    decision=VoteDecision.REJECT,
                    confidence=0.8,
                    reasoning="Too risky",
                    concerns=["May cause downtime", "Not authorized"],
                )
            ],
        )

        request = await voting.request_human_approval(action, consensus_result)

        assert "concerns" in request
        assert "May cause downtime" in request["concerns"]
        assert "Not authorized" in request["concerns"]


class TestConsensusEdgeCases:
    """Edge-case tests for consensus voting logic."""

    @staticmethod
    def _system(config=None):
        return VotingSystem(MockLLMClient(), config or VotingConfig())

    @staticmethod
    def _action(risk=ActionRisk.HIGH):
        return AgentAction(
            action_type="run_tool",
            confidence=0.8,
            risk_level=risk,
            reasoning="test",
        )

    @staticmethod
    def _vote(vid, decision, confidence=0.8):
        return Vote(
            voter_id=vid,
            decision=decision,
            confidence=confidence,
            reasoning=f"{decision}",
        )

    def test_unanimous_approval_high_confidence(self):
        vs = self._system()
        votes = [self._vote(f"v{i}", VoteDecision.APPROVE, 0.9) for i in range(3)]
        r = vs._analyze_votes_with_params(votes, self._action(), 2, 0.6)
        assert r.status == ConsensusStatus.APPROVED
        assert r.approve_count == 3
        assert r.final_decision is True

    def test_unanimous_rejection(self):
        vs = self._system()
        votes = [self._vote(f"v{i}", VoteDecision.REJECT, 0.9) for i in range(3)]
        r = vs._analyze_votes_with_params(votes, self._action(), 2, 0.6)
        assert r.status == ConsensusStatus.REJECTED
        assert r.reject_count == 3
        assert r.final_decision is False

    def test_split_vote_no_consensus(self):
        vs = self._system()
        votes = [
            self._vote("v0", VoteDecision.APPROVE, 0.7),
            self._vote("v1", VoteDecision.REJECT, 0.7),
            self._vote("v2", VoteDecision.ABSTAIN, 0.5),
        ]
        # CRITICAL risk → NO_CONSENSUS escalates to PENDING_HUMAN
        r = vs._analyze_votes_with_params(votes, self._action(ActionRisk.CRITICAL), 2, 0.6)
        assert r.status == ConsensusStatus.PENDING_HUMAN

    def test_no_consensus_critical_becomes_pending_human(self):
        vs = self._system()
        votes = [
            self._vote("v0", VoteDecision.APPROVE, 0.9),
            self._vote("v1", VoteDecision.ABSTAIN, 0.3),
            self._vote("v2", VoteDecision.ABSTAIN, 0.3),
        ]
        r = vs._analyze_votes_with_params(votes, self._action(ActionRisk.CRITICAL), 2, 0.6)
        assert r.status == ConsensusStatus.PENDING_HUMAN
        assert "CRITICAL" in (r.escalation_reason or "")

    def test_no_consensus_low_risk_majority_approval(self):
        """Approve > reject at LOW risk → falls back to majority APPROVED."""
        vs = self._system()
        votes = [
            self._vote("v0", VoteDecision.APPROVE, 0.5),
            self._vote("v1", VoteDecision.APPROVE, 0.4),
            self._vote("v2", VoteDecision.ABSTAIN, 0.3),
        ]
        # k=3 so 2 approvals won't meet threshold; confidence low → NO_CONSENSUS
        # but approve(2) > reject(0) at LOW risk → majority fallback
        r = vs._analyze_votes_with_params(votes, self._action(ActionRisk.LOW), 3, 0.8)
        assert r.status == ConsensusStatus.APPROVED
        assert r.final_decision is True
        assert "majority" in (r.escalation_reason or "").lower()

    def test_no_votes_collected(self):
        vs = self._system()
        r = vs._analyze_votes_with_params([], self._action(), 2, 0.6)
        assert r.status == ConsensusStatus.NO_CONSENSUS
        assert r.escalation_reason == "No votes collected"

    def test_single_voter_k1_approve(self):
        vs = self._system(VotingConfig(num_voters=1, k_threshold=1))
        votes = [self._vote("v0", VoteDecision.APPROVE, 0.9)]
        r = vs._analyze_votes_with_params(votes, self._action(), 1, 0.6)
        assert r.status == ConsensusStatus.APPROVED
        assert r.final_decision is True

    def test_single_voter_k1_reject(self):
        vs = self._system(VotingConfig(num_voters=1, k_threshold=1))
        votes = [self._vote("v0", VoteDecision.REJECT, 0.9)]
        r = vs._analyze_votes_with_params(votes, self._action(), 1, 0.6)
        assert r.status == ConsensusStatus.REJECTED

    def test_confidence_aggregation(self):
        vs = self._system()
        votes = [
            self._vote("v0", VoteDecision.APPROVE, 0.6),
            self._vote("v1", VoteDecision.APPROVE, 0.8),
            self._vote("v2", VoteDecision.APPROVE, 1.0),
        ]
        r = vs._analyze_votes_with_params(votes, self._action(), 2, 0.6)
        assert r.average_confidence == pytest.approx(0.8, abs=0.01)

    def test_confidence_too_low_despite_approvals_at_critical(self):
        vs = self._system()
        votes = [
            self._vote("v0", VoteDecision.APPROVE, 0.3),
            self._vote("v1", VoteDecision.APPROVE, 0.2),
        ]
        r = vs._analyze_votes_with_params(votes, self._action(ActionRisk.CRITICAL), 2, 0.6)
        assert r.status == ConsensusStatus.PENDING_HUMAN

    @pytest.mark.asyncio
    async def test_all_voters_timeout(self):
        """When LLM raises for every voter, _get_vote returns ABSTAIN votes."""
        from unittest.mock import AsyncMock

        llm = AsyncMock()
        llm.generate_structured.side_effect = TimeoutError("timeout")
        vs = VotingSystem(llm=llm, config=VotingConfig(num_voters=3, k_threshold=2))
        result = await vs.vote_on_action(self._action(ActionRisk.HIGH))
        # All voters produce ABSTAIN → no approvals, no rejects → NO_CONSENSUS
        assert result.status in (ConsensusStatus.NO_CONSENSUS, ConsensusStatus.PENDING_HUMAN)

    def test_voting_config_consensus_threshold_low_risk_skips(self):
        cfg = VotingConfig()
        n, _k, _c = cfg.consensus_threshold[ActionRisk.LOW.value]
        assert n == 0  # Skip consensus for LOW risk
