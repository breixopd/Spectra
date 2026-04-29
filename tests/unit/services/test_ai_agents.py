"""Tests for AI agent classes and their patterns."""

import inspect
from unittest.mock import patch

import pytest

from app.services.ai.agents.base import (
    ROLE_TASK_MAP,
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
    ApprovalRequest,
    SteeringAction,
    ToolAction,
)
from tests.mocks.llm import MockLLMClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "mission_id": "m-1",
        "target": "192.168.1.1",
        "phase": "discovery",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# Base module imports
# ---------------------------------------------------------------------------


class TestBaseImports:
    def test_agent_base_importable(self):
        assert Agent is not None

    def test_agent_role_values(self):
        assert AgentRole.SCOPE == "scope"
        assert AgentRole.DEBRIEF == "debrief"
        assert AgentRole.REPORTER == "reporter"

    def test_action_risk_values(self):
        assert ActionRisk.LOW == "low"
        assert ActionRisk.CRITICAL == "critical"

    def test_tool_action_defaults(self):
        ta = ToolAction(
            confidence=0.9,
            reasoning="test",
            tool_name="nmap",
            target="10.0.0.1",
        )
        assert ta.action_type == "run_tool"
        assert ta.risk_level == ActionRisk.LOW

    def test_steering_action_defaults(self):
        sa = SteeringAction(
            confidence=0.8,
            reasoning="pivot",
            new_phase="exploitation",
        )
        assert sa.action_type == "steer"

    def test_approval_request_defaults(self):
        ar = ApprovalRequest(
            confidence=0.5,
            reasoning="high-risk",
            pending_action={"foo": "bar"},
        )
        assert ar.timeout_seconds == 300
        assert ar.default_on_timeout is False

    def test_agent_result_dataclass(self):
        r = AgentResult(success=True)
        assert r.action is None
        assert r.error is None
        assert r.metadata == {}


# ---------------------------------------------------------------------------
# AgentContext
# ---------------------------------------------------------------------------


class TestAgentContext:
    def test_defaults(self):
        ctx = AgentContext(mission_id="m-1")
        assert ctx.phase == "discovery"
        assert ctx.stealth_mode is False
        assert ctx.max_concurrency == 3
        assert ctx.previous_findings == []
        assert ctx.available_tools == []

    def test_optional_fields(self):
        ctx = _make_context(session_id="s-1", mission="full scan")
        assert ctx.session_id == "s-1"
        assert ctx.mission == "full scan"


# ---------------------------------------------------------------------------
# Role → task_type mapping
# ---------------------------------------------------------------------------


class TestRoleTaskMap:
    def test_all_roles_mapped(self):
        for role in AgentRole:
            assert role in ROLE_TASK_MAP, f"{role} missing from ROLE_TASK_MAP"


# ---------------------------------------------------------------------------
# Concrete agent imports & class structure
# ---------------------------------------------------------------------------


def _get_all_agent_classes():
    """Import every concrete agent and return (name, cls) pairs."""
    from app.services.ai.agents.debrief import DebriefAgent
    from app.services.ai.agents.exploit_crafter import ExploitCrafter
    from app.services.ai.agents.mission_controller import MissionController
    from app.services.ai.agents.post_exploitation import PostExploitationAgent
    from app.services.ai.agents.reporter import ReporterAgent
    from app.services.ai.agents.safety import SafetySupervisorAgent
    from app.services.ai.agents.scope import ScopeAgent
    from app.services.ai.agents.tool_selector import ToolSelectorAgent
    from app.services.ai.agents.vector_generator import VectorGeneratorAgent

    return [
        ("ScopeAgent", ScopeAgent),
        ("DebriefAgent", DebriefAgent),
        ("MissionController", MissionController),
        ("SafetySupervisorAgent", SafetySupervisorAgent),
        ("ToolSelectorAgent", ToolSelectorAgent),
        ("ExploitCrafter", ExploitCrafter),
        ("ReporterAgent", ReporterAgent),
        ("PostExploitationAgent", PostExploitationAgent),
        ("VectorGeneratorAgent", VectorGeneratorAgent),
    ]


class TestConcreteAgentStructure:
    """Verify every concrete agent conforms to the base pattern."""

    @pytest.mark.parametrize(
        "name,cls",
        _get_all_agent_classes(),
        ids=[n for n, _ in _get_all_agent_classes()],
    )
    def test_subclasses_agent(self, name, cls):
        assert issubclass(cls, Agent)

    @pytest.mark.parametrize(
        "name,cls",
        _get_all_agent_classes(),
        ids=[n for n, _ in _get_all_agent_classes()],
    )
    def test_has_role(self, name, cls):
        assert hasattr(cls, "role")
        assert isinstance(cls.role, AgentRole)

    @pytest.mark.parametrize(
        "name,cls",
        _get_all_agent_classes(),
        ids=[n for n, _ in _get_all_agent_classes()],
    )
    def test_has_name_and_description(self, name, cls):
        assert isinstance(cls.name, str) and cls.name != "BaseAgent"
        assert isinstance(cls.description, str) and len(cls.description) > 5

    @pytest.mark.parametrize(
        "name,cls",
        _get_all_agent_classes(),
        ids=[n for n, _ in _get_all_agent_classes()],
    )
    def test_execute_is_async(self, name, cls):
        assert inspect.iscoroutinefunction(cls.execute)

    @pytest.mark.parametrize(
        "name,cls",
        _get_all_agent_classes(),
        ids=[n for n, _ in _get_all_agent_classes()],
    )
    def test_instantiation_with_mock_llm(self, name, cls):
        llm = MockLLMClient()
        agent = cls(llm)
        assert agent.llm is llm


# ---------------------------------------------------------------------------
# Temperature logic
# ---------------------------------------------------------------------------


class TestAgentTemperature:
    def test_scope_agent_low_temperature(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        assert agent._get_temperature(None) == pytest.approx(0.1)

    def test_debrief_agent_medium_temperature(self):
        from app.services.ai.agents.debrief import DebriefAgent

        agent = DebriefAgent(MockLLMClient())
        assert agent._get_temperature(None) == pytest.approx(0.4)

    def test_exploit_crafter_high_temperature(self):
        from app.services.ai.agents.exploit_crafter import ExploitCrafter

        agent = ExploitCrafter(MockLLMClient())
        assert agent._get_temperature(None) == pytest.approx(0.7)

    def test_temperature_increases_on_retry(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        t1 = agent._get_temperature(None, attempt=1)
        t2 = agent._get_temperature(None, attempt=2)
        assert t2 > t1

    def test_temperature_capped_at_one(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        assert agent._get_temperature(None, attempt=50) <= 1.0


# ---------------------------------------------------------------------------
# task_type routing
# ---------------------------------------------------------------------------


class TestTaskTypeRouting:
    def test_scope_agent_task_type(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        assert agent._task_type == "scope"

    def test_debrief_agent_task_type(self):
        from app.services.ai.agents.debrief import DebriefAgent

        agent = DebriefAgent(MockLLMClient())
        assert agent._task_type == "reporting"

    def test_mission_controller_task_type(self):
        from app.services.ai.agents.mission_controller import MissionController

        agent = MissionController(MockLLMClient())
        assert agent._task_type == "planning"


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------


class TestActionValidation:
    @pytest.mark.asyncio
    async def test_validate_action_passes_above_threshold(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(action_type="test", confidence=0.5, reasoning="ok")
        valid, err = await agent.validate_action(action)
        assert valid is True
        assert err is None

    @pytest.mark.asyncio
    async def test_validate_action_fails_below_threshold(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(action_type="test", confidence=0.2, reasoning="low")
        valid, err = await agent.validate_action(action)
        assert valid is False
        assert err is not None
        assert "Confidence too low" in err


# ---------------------------------------------------------------------------
# Approval / consensus helpers
# ---------------------------------------------------------------------------


class TestApprovalConsensus:
    def test_requires_approval_high_risk(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            reasoning="dangerous",
            risk_level=ActionRisk.CRITICAL,
        )
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.REQUIRE_APPROVAL = True
            assert agent.requires_approval(action) is True

    def test_requires_approval_false_when_disabled(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            reasoning="dangerous",
            risk_level=ActionRisk.CRITICAL,
        )
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.REQUIRE_APPROVAL = False
            agent._mission_requires_approval = False
            assert agent.requires_approval(action) is False

    def test_requires_approval_when_mission_requires_without_env_kill_switch(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            reasoning="dangerous",
            risk_level=ActionRisk.CRITICAL,
        )
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.REQUIRE_APPROVAL = False
            agent._mission_requires_approval = True
            assert agent.requires_approval(action) is True

    def test_requires_consensus_high_risk(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            reasoning="test",
            risk_level=ActionRisk.HIGH,
        )
        assert agent.requires_consensus(action) is True

    def test_no_consensus_for_low_risk(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            reasoning="test",
            risk_level=ActionRisk.LOW,
        )
        assert agent.requires_consensus(action) is False


# ---------------------------------------------------------------------------
# _llm_generate helpers
# ---------------------------------------------------------------------------


class TestLLMGenerateHelpers:
    @pytest.mark.asyncio
    async def test_llm_generate_returns_response(self):
        from app.services.ai.agents.scope import ScopeAgent

        mock_llm = MockLLMClient()
        agent = ScopeAgent(mock_llm)
        result = await agent._llm_generate(prompt="test prompt")
        assert result.content == "Mock response"
        assert len(mock_llm.call_history) == 1

    @pytest.mark.asyncio
    async def test_llm_generate_structured_returns_model(self):
        from app.services.ai.agents.scope import ScopeAction, ScopeAgent

        mock_llm = MockLLMClient(
            structured_responses={
                "ScopeAction": {
                    "action_type": "define_scope",
                    "confidence": 0.9,
                    "risk_level": "low",
                    "reasoning": "test",
                    "targets": [],
                    "total_hosts": 0,
                    "warnings": [],
                }
            }
        )
        agent = ScopeAgent(mock_llm)
        result = await agent._llm_generate_structured(prompt="test", response_model=ScopeAction)
        assert isinstance(result, ScopeAction)


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_system_prompt_contains_name(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        ctx = _make_context()
        prompt = agent._build_system_prompt(ctx)
        assert "ScopeAgent" in prompt

    def test_system_prompt_contains_target(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        ctx = _make_context(target="example.com")
        prompt = agent._build_system_prompt(ctx)
        assert "example.com" in prompt


# ---------------------------------------------------------------------------
# ScopeAgent._extract_targets (regex-based, no LLM needed)
# ---------------------------------------------------------------------------


class TestScopeAgentExtraction:
    def test_extracts_ip(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        targets, _warnings = agent._extract_targets("scan 10.0.0.1")  # type: ignore[attr-defined]
        values = [t.value for t in targets]
        assert "10.0.0.1" in values

    def test_extracts_cidr(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        targets, _ = agent._extract_targets("scan 10.0.0.0/24")  # type: ignore[attr-defined]
        values = [t.value for t in targets]
        assert "10.0.0.0/24" in values

    def test_extracts_domain(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        targets, _ = agent._extract_targets("scan example.com")  # type: ignore[attr-defined]
        values = [t.value for t in targets]
        assert "example.com" in values

    def test_no_targets_returns_empty(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        targets, _ = agent._extract_targets("nothing useful")  # type: ignore[attr-defined]
        assert targets == []


# ---------------------------------------------------------------------------
# Mock execution of an agent's main execute method
# ---------------------------------------------------------------------------


class TestScopeAgentExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        from app.services.ai.agents.scope import ScopeAgent, ScopeInput

        agent = ScopeAgent(MockLLMClient())
        ctx = _make_context()
        inp = ScopeInput(raw_input="scan 10.0.0.1")
        result = await agent.execute(ctx, inp)
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.action is not None
        assert result.action.confidence > 0

    @pytest.mark.asyncio
    async def test_execute_no_targets(self):
        from app.services.ai.agents.scope import ScopeAgent, ScopeInput

        agent = ScopeAgent(MockLLMClient())
        ctx = _make_context()
        inp = ScopeInput(raw_input="")
        result = await agent.execute(ctx, inp)
        assert isinstance(result, AgentResult)


class TestDebriefAgentExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        from app.services.ai.agents.debrief import DebriefAgent, DebriefInput

        agent = DebriefAgent(
            MockLLMClient(
                structured_responses={
                    "DebriefOutput": {
                        "action_type": "debrief",
                        "confidence": 0.8,
                        "risk_level": "medium",
                        "reasoning": "mock debrief",
                        "executive_summary": "Test summary",
                        "what_worked": ["nmap"],
                        "what_failed": [],
                        "human_comparison": "n/a",
                        "remediation_priorities": [],
                        "lessons_learned": [],
                        "risk_rating": "medium",
                        "next_steps": [],
                    }
                }
            )
        )
        ctx = _make_context()
        inp = DebriefInput(
            target="10.0.0.1",
            directive="full scan",
            findings=[{"severity": "high", "name": "SQLi"}],
            tools_run=["nmap", "sqlmap"],
        )
        result = await agent.execute(ctx, inp)
        assert isinstance(result, AgentResult)
        assert result.success is True


# ---------------------------------------------------------------------------
# __call__ delegates to execute
# ---------------------------------------------------------------------------


class TestAgentCallable:
    @pytest.mark.asyncio
    async def test_call_delegates_to_execute(self):
        from app.services.ai.agents.scope import ScopeAgent, ScopeInput

        agent = ScopeAgent(MockLLMClient())
        ctx = _make_context()
        inp = ScopeInput(raw_input="scan 10.0.0.1")
        result = await agent(ctx, inp)
        assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# _execute_with_retry
# ---------------------------------------------------------------------------


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        call_count = 0

        async def ok():
            nonlocal call_count
            call_count += 1
            return "done"

        result = await agent._execute_with_retry(ok, max_retries=2, backoff_factor=0.01)
        assert result == "done"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("oops")
            return "ok"

        result = await agent._execute_with_retry(flaky, max_retries=2, backoff_factor=0.01)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        from app.services.ai.agents.scope import ScopeAgent

        agent = ScopeAgent(MockLLMClient())

        async def always_fail():
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await agent._execute_with_retry(always_fail, max_retries=1, backoff_factor=0.01)
