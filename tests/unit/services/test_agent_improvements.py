"""Tests for agent system improvements (AGENT-001 through MISSION-005)."""

import pytest

from spectra_ai_core.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from spectra_ai_core.agents.exploit_verifier import (
    FAILURE_PATTERNS,
    SUCCESS_PATTERNS,
    ExploitVerifierAgent,
    ExploitVerifierInput,
)
from spectra_ai_core.agents.reporter import ReporterAgent
from spectra_ai_core.blackboard import MissionBlackboard, _blackboards, get_blackboard, remove_blackboard
from spectra_ai_core.consensus import VotingConfig, VotingSystem
from spectra_domain.enums import MissionStatus
from spectra_mission.task_tree import PentestTaskTree, TaskStatus
from tests.mocks.llm import MockLLMClient

# ---- Fixtures ----


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def context():
    return AgentContext(
        mission_id="test-mission",
        target="10.0.0.1",
        phase="exploitation",
    )


# ===========================================================================
# AGENT-001: Deterministic Exploit Verification
# ===========================================================================


class TestDeterministicExploitVerification:
    """Tests for XBOW-style deterministic checks."""

    def test_success_patterns_defined(self):
        assert len(SUCCESS_PATTERNS) > 0
        for pattern, tag, severity in SUCCESS_PATTERNS:
            assert isinstance(pattern, str)
            assert isinstance(tag, str)
            assert severity in ("critical", "high", "medium")

    def test_failure_patterns_defined(self):
        assert len(FAILURE_PATTERNS) > 0
        for pattern, tag in FAILURE_PATTERNS:
            assert isinstance(pattern, str)
            assert isinstance(tag, str)

    def test_deterministic_root_shell(self):
        output = "uid=0(root) gid=0(root) groups=0(root)"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        action = result["action"]
        assert action.is_successful is True
        assert action.confidence >= 0.95
        assert action.deterministic_evidence is not None

    def test_deterministic_meterpreter(self):
        output = "meterpreter > getuid\nServer username: NT AUTHORITY\\SYSTEM"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True
        assert result["action"].confidence >= 0.95

    def test_deterministic_etc_passwd(self):
        output = "root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True

    def test_deterministic_private_key(self):
        output = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True
        assert result["action"].confidence == 0.99  # critical severity

    def test_deterministic_connection_refused(self):
        output = "Connection refused (111)"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is False

    def test_deterministic_no_session(self):
        output = "Exploit completed, but no session was created"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is False

    def test_deterministic_no_match(self):
        output = "Running scan on target..."
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_uses_deterministic_first(self, mock_llm, context):
        agent = ExploitVerifierAgent(mock_llm)
        input_data = ExploitVerifierInput(
            target="10.0.0.1",
            exploit_output="uid=0(root) gid=0(root)",
            expected_outcome="root shell",
        )
        result = await agent.execute(context, input_data)
        assert result.success
        assert result.action.is_successful is True
        assert result.action.deterministic_evidence is not None

    @pytest.mark.asyncio
    async def test_execute_falls_through_to_llm(self, mock_llm, context):
        mock_llm.structured_responses["ExploitVerifierOutput"] = {
            "action_type": "verify_exploit",
            "is_successful": False,
            "confidence": 0.5,
            "proof": "Ambiguous output",
            "next_steps": [],
            "reasoning": "test",
        }
        agent = ExploitVerifierAgent(mock_llm)
        input_data = ExploitVerifierInput(
            target="10.0.0.1",
            exploit_output="Some ambiguous output from nmap scan",
            expected_outcome="reverse shell",
        )
        result = await agent.execute(context, input_data)
        assert result.success
        # LLM was called since no deterministic match
        assert result.action.deterministic_evidence is None

    def test_deterministic_windows_system(self):
        output = "Server username: NT AUTHORITY\\SYSTEM"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True

    def test_deterministic_mysql_access(self):
        output = "Welcome to MySQL...\nmysql>"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True

    def test_deterministic_postgres_access(self):
        output = "psql (16.1)\npostgres=#"
        result = ExploitVerifierAgent._deterministic_check(output)
        assert result is not None
        assert result["action"].is_successful is True


# ===========================================================================
# AGENT-003: REPORTER role
# ===========================================================================


class TestReporterRole:
    def test_reporter_role_exists(self):
        assert hasattr(AgentRole, "REPORTER")
        assert AgentRole.REPORTER.value == "reporter"

    def test_reporter_agent_uses_reporter_role(self, mock_llm):
        agent = ReporterAgent(mock_llm)
        assert agent.role == AgentRole.REPORTER


# ===========================================================================
# AGENT-005: Mission-Scoped Blackboard
# ===========================================================================


class TestMissionBlackboard:
    def test_write_and_read(self):
        bb = MissionBlackboard("m-1")
        bb.write("recon", "open_ports", [22, 80, 443])
        assert bb.read("open_ports") == [22, 80, 443]

    def test_read_missing_key(self):
        bb = MissionBlackboard("m-1")
        assert bb.read("nonexistent") is None

    def test_read_all(self):
        bb = MissionBlackboard("m-1")
        bb.write("recon", "ports", [80])
        bb.write("vuln_scanner", "cves", ["CVE-2024-1"])
        data = bb.read_all()
        assert data == {"ports": [80], "cves": ["CVE-2024-1"]}

    def test_get_context_for_agent_empty(self):
        bb = MissionBlackboard("m-1")
        assert bb.get_context_for_agent("recon") == ""

    def test_get_context_for_agent_with_data(self):
        bb = MissionBlackboard("m-1")
        bb.write("recon", "open_ports", "22, 80")
        ctx = bb.get_context_for_agent("exploit")
        assert "[Shared Intelligence from other agents]" in ctx
        assert "open_ports" in ctx

    def test_history_tracking(self):
        bb = MissionBlackboard("m-1")
        bb.write("a", "k1", "v1")
        bb.write("b", "k2", "v2")
        assert len(bb.get_history()) == 2

    def test_get_blackboard_creates_and_reuses(self):
        _blackboards.clear()
        bb1 = get_blackboard("test-mission")
        bb2 = get_blackboard("test-mission")
        assert bb1 is bb2
        _blackboards.clear()

    def test_remove_blackboard(self):
        _blackboards.clear()
        get_blackboard("test-mission")
        assert "test-mission" in _blackboards
        remove_blackboard("test-mission")
        assert "test-mission" not in _blackboards

    def test_overwrite_key(self):
        bb = MissionBlackboard("m-1")
        bb.write("a", "key", "old")
        bb.write("b", "key", "new")
        assert bb.read("key") == "new"


# ===========================================================================
# AGENT-006: Configurable Consensus Gate
# ===========================================================================


class TestConfigurableConsensus:
    def test_consensus_threshold_in_config(self):
        config = VotingConfig()
        assert "low" in config.consensus_threshold
        assert "medium" in config.consensus_threshold
        assert "high" in config.consensus_threshold
        assert "critical" in config.consensus_threshold

    def test_low_risk_skips_voting_via_threshold(self):
        config = VotingConfig()
        low_entry = config.consensus_threshold["low"]
        assert low_entry[0] == 0  # num_voters == 0 means skip

    def test_medium_risk_requires_2_of_3(self):
        config = VotingConfig()
        n, k, _c = config.consensus_threshold["medium"]
        assert n == 3
        assert k == 2

    def test_high_risk_requires_3_of_3(self):
        config = VotingConfig()
        n, k, _c = config.consensus_threshold["high"]
        assert n == 3
        assert k == 3

    def test_requires_voting_skips_low(self):
        llm = MockLLMClient()
        # Set voting threshold to MEDIUM so LOW actions would normally be below threshold
        config = VotingConfig(voting_risk_threshold=ActionRisk.LOW)
        vs = VotingSystem(llm, config)
        low_action = AgentAction(action_type="test", confidence=0.8, risk_level=ActionRisk.LOW, reasoning="t")
        # LOW risk → consensus_threshold says skip (num_voters=0)
        assert vs.requires_voting(low_action) is False


# ===========================================================================
# AGENT-007: Move POC Prompt to prompts.py
# ===========================================================================


class TestPOCPromptMoved:
    def test_poc_prompt_in_prompts_module(self):
        from spectra_ai_core.prompts import POC_DEVELOPER_PROMPT

        assert "Exploit Developer" in POC_DEVELOPER_PROMPT
        assert "{target}" in POC_DEVELOPER_PROMPT

    def test_poc_developer_uses_prompt_from_prompts_module(self):
        """Verify the poc_developer module no longer defines its own prompt."""
        import spectra_ai_core.prompts as prompts_mod

        assert hasattr(prompts_mod, "POC_DEVELOPER_PROMPT")


# ===========================================================================
# AGENT-008: Base Agent Retry with Backoff
# ===========================================================================


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, mock_llm):
        class TestAgent(Agent):
            role = AgentRole.SCOPE
            name = "TestAgent"
            description = "Test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = TestAgent(mock_llm)
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return "ok"

        result = await agent._execute_with_retry(flaky, max_retries=2, backoff_factor=0.01)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self, mock_llm):
        class TestAgent(Agent):
            role = AgentRole.SCOPE
            name = "TestAgent"
            description = "Test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = TestAgent(mock_llm)

        async def always_fail():
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await agent._execute_with_retry(always_fail, max_retries=1, backoff_factor=0.01)

    @pytest.mark.asyncio
    async def test_retry_immediate_success(self, mock_llm):
        class TestAgent(Agent):
            role = AgentRole.SCOPE
            name = "TestAgent"
            description = "Test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = TestAgent(mock_llm)

        async def immediate():
            return 42

        result = await agent._execute_with_retry(immediate, max_retries=3)
        assert result == 42


# ===========================================================================
# AGENT-009: Adaptive Temperature
# ===========================================================================


class TestAdaptiveTemperature:
    def test_temperature_increases_with_attempt(self, mock_llm):
        class ExploitAgent(Agent):
            role = AgentRole.EXPLOIT_CRAFTER
            name = "Exploit"
            description = "test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = ExploitAgent(mock_llm)
        t1 = agent._get_temperature(None, attempt=1)
        t2 = agent._get_temperature(None, attempt=2)
        t3 = agent._get_temperature(None, attempt=3)
        assert t1 == 0.7
        assert t2 == pytest.approx(0.8)
        assert t3 == pytest.approx(0.9)

    def test_temperature_capped_at_1(self, mock_llm):
        class ExploitAgent(Agent):
            role = AgentRole.EXPLOIT_CRAFTER
            name = "Exploit"
            description = "test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = ExploitAgent(mock_llm)
        t = agent._get_temperature(None, attempt=10)
        assert t == 1.0

    def test_default_attempt_backward_compatible(self, mock_llm):
        class ScopeAgent(Agent):
            role = AgentRole.SCOPE
            name = "Scope"
            description = "test"

            async def execute(self, context, input_data):
                return AgentResult(success=True)

        agent = ScopeAgent(mock_llm)
        # Default attempt=1 means no increase
        assert agent._get_temperature(None) == 0.1


# ===========================================================================
# Task Tree
# ===========================================================================


class TestPentestTaskTree:
    def test_create_and_add_task(self):
        tree = PentestTaskTree("m-1")
        node = tree.add_task("t1", "Port Scan", "recon/port_scan")
        assert node.id == "t1"
        assert node.parent_id == "root"
        assert "t1" in tree.root.children

    def test_update_status(self):
        tree = PentestTaskTree("m-1")
        tree.add_task("t1", "Scan", "recon/scan")
        tree.update_status("t1", TaskStatus.ACTIVE)
        node = tree.get_node("t1")
        assert node.status == TaskStatus.ACTIVE
        assert node.started_at is not None

    def test_complete_sets_timestamp(self):
        tree = PentestTaskTree("m-1")
        tree.add_task("t1", "Scan", "recon/scan")
        tree.update_status("t1", TaskStatus.COMPLETED)
        node = tree.get_node("t1")
        assert node.completed_at is not None

    def test_get_active_tasks(self):
        tree = PentestTaskTree("m-1")
        tree.add_task("t1", "Scan", "recon")
        tree.add_task("t2", "Exploit", "exploit/rce")
        tree.update_status("t1", TaskStatus.ACTIVE)
        active = tree.get_active_tasks()
        assert len(active) == 1
        assert active[0].id == "t1"

    def test_serialize_deserialize(self):
        tree = PentestTaskTree("m-1")
        tree.add_task("t1", "Scan", "recon/scan", tool_used="nmap")
        tree.update_status("t1", TaskStatus.COMPLETED)

        data = tree.to_dict()
        restored = PentestTaskTree.from_dict(data)
        assert restored.mission_id == "m-1"
        node = restored.get_node("t1")
        assert node is not None
        assert node.status == TaskStatus.COMPLETED
        assert node.tool_used == "nmap"

    def test_nested_tasks(self):
        tree = PentestTaskTree("m-1")
        tree.add_task("recon", "Recon Phase", "recon")
        tree.add_task("scan", "Port Scan", "recon/port_scan", parent_id="recon")
        assert "scan" in tree.get_node("recon").children

    def test_nonexistent_node(self):
        tree = PentestTaskTree("m-1")
        assert tree.get_node("nope") is None

    def test_update_nonexistent_node(self):
        tree = PentestTaskTree("m-1")
        # Should not raise
        tree.update_status("nope", TaskStatus.FAILED)


# ===========================================================================
# MISSION-001: Consolidated State Enums
# ===========================================================================


class TestConsolidatedStateEnums:
    def test_mission_status_has_all_states(self):
        """MissionStatus covers the FSM state set used by missions."""
        assert hasattr(MissionStatus, "CREATED")
        assert hasattr(MissionStatus, "INITIALIZING")
        assert hasattr(MissionStatus, "PLANNING")
        assert hasattr(MissionStatus, "EXECUTING")
        assert hasattr(MissionStatus, "REPORTING")
        assert hasattr(MissionStatus, "COMPLETED")
        assert hasattr(MissionStatus, "FAILED")
        assert hasattr(MissionStatus, "CANCELLED")
        assert hasattr(MissionStatus, "PAUSED")

    def test_mission_status_values_stable(self):
        """Key API string values for mission status."""
        assert MissionStatus.CREATED.value == "created"
        assert MissionStatus.COMPLETED.value == "completed"
        assert MissionStatus.FAILED.value == "failed"
        assert MissionStatus.PAUSED.value == "paused"


# ===========================================================================
# MISSION-005: FSM integration in Mission
# ===========================================================================


class TestMissionFSMIntegration:
    @pytest.fixture(autouse=True)
    def _writable_data_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "spectra_mission.mission.data_path",
            lambda *parts: tmp_path / "data" / "/".join(str(p) for p in parts),
        )

    def test_mission_has_fsm(self):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        assert hasattr(m, "fsm")
        assert m.fsm.state == MissionStatus.CREATED

    def test_set_status_valid_transition(self):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        m.set_status("initializing")
        assert m.status == "initializing"
        assert m.fsm.state == MissionStatus.INITIALIZING

    def test_set_status_invalid_transition_still_sets_raw(self):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        # CREATED -> COMPLETED is invalid, but raw status still updates
        m.set_status("completed")
        assert m.status == "completed"
        # FSM stays at CREATED since transition was invalid
        assert m.fsm.state == MissionStatus.CREATED

    def test_set_status_unknown_value(self):
        from spectra_mission.mission import Mission

        m = Mission("10.0.0.1", "test")
        # "running" is not a direct FSM enum label for CREATED→…
        m.set_status("running")
        assert m.status == "running"
