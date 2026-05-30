"""Tests for mission executor handlers (TaskDispatcher)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_mission.executor.handlers import (
    MAX_CHAIN_DEPTH,
    PHASE_TRANSITION_RULES,
    TaskDispatcher,
    _get_known_tools,
)


class TestPhaseTransitionRules:
    def test_recon_rules(self):
        rules = PHASE_TRANSITION_RULES["recon"]
        assert rules["min_tools"] == 2
        assert rules["max_tools"] == 6
        assert rules["transition_trigger"] == "services_found"

    def test_vuln_scan_rules(self):
        rules = PHASE_TRANSITION_RULES["vuln_scan"]
        assert rules["min_tools"] == 1
        assert rules["max_tools"] == 4

    def test_exploitation_rules(self):
        rules = PHASE_TRANSITION_RULES["exploitation"]
        assert rules["max_failures"] == 3
        assert rules["transition_trigger"] == "shell_obtained"

    def test_post_exploitation_rules(self):
        rules = PHASE_TRANSITION_RULES["post_exploitation"]
        assert rules["min_tools"] == 1
        assert rules["max_tools"] == 3

    def test_max_chain_depth(self):
        assert MAX_CHAIN_DEPTH == 10


class TestGetKnownTools:
    def test_returns_set_of_strings(self):
        tools = _get_known_tools()
        assert isinstance(tools, set)

    def test_fallback_set_is_correct(self):
        """Verify the hardcoded fallback set has the expected tools."""
        # Directly test the fallback path by making get_registry raise
        import spectra_tools_core.registry as reg_mod

        original = reg_mod._registry_instance
        try:
            reg_mod._registry_instance = None
            with patch.object(reg_mod, "ToolRegistry", side_effect=RuntimeError("no")):
                tools = _get_known_tools()
                assert len(tools) >= 10
                assert "nmap" in tools
                assert "nuclei" in tools
                assert "hydra" in tools
                assert "sqlmap" in tools
        finally:
            reg_mod._registry_instance = original


class TestTaskDispatcher:
    @pytest.fixture
    def dispatcher(self):
        tool_service = AsyncMock()
        exploit_manager = AsyncMock()
        consensus = AsyncMock()
        agents = {
            "tool_selector": AsyncMock(),
            "exploit_crafter": AsyncMock(),
        }
        return TaskDispatcher(tool_service, exploit_manager, consensus, agents)

    def test_get_handler_tool_selector(self, dispatcher):
        handler = dispatcher._get_task_handler("tool_selector")
        assert handler is not None

    def test_get_handler_exploit_crafter(self, dispatcher):
        handler = dispatcher._get_task_handler("exploit_crafter")
        assert handler is not None

    def test_get_handler_reporter(self, dispatcher):
        handler = dispatcher._get_task_handler("reporter")
        assert handler is not None

    def test_get_handler_scope(self, dispatcher):
        handler = dispatcher._get_task_handler("scope")
        assert handler is not None

    def test_get_handler_scope_agent_alias(self, dispatcher):
        h1 = dispatcher._get_task_handler("scope")
        h2 = dispatcher._get_task_handler("scope_agent")
        assert h1 == h2

    def test_get_handler_unknown_returns_none(self, dispatcher):
        handler = dispatcher._get_task_handler("nonexistent_handler_xyz")
        assert handler is None

    def test_unknown_agent_type_fallback(self, dispatcher):
        # Agent types ending in _agent fall back to tool_selector
        handler = dispatcher._get_task_handler("custom_agent")
        assert handler is not None

    def test_common_hallucinated_types_fallback(self, dispatcher):
        for t in ["discovery", "enumeration", "vulnerability"]:
            handler = dispatcher._get_task_handler(t)
            assert handler is not None

    def test_extract_tool_hint_nmap(self, dispatcher):
        with patch(
            "spectra_mission.executor.handlers._get_known_tools", return_value={"nmap", "nuclei", "sqlmap"}
        ):
            hint = dispatcher._extract_tool_hint_from_description("Run nmap scan on target")
            assert hint == "nmap"

    def test_extract_tool_hint_using_pattern(self, dispatcher):
        with patch(
            "spectra_mission.executor.handlers._get_known_tools", return_value={"nmap", "nuclei", "sqlmap"}
        ):
            hint = dispatcher._extract_tool_hint_from_description("Scan ports using nmap")
            assert hint == "nmap"

    def test_extract_tool_hint_with_pattern(self, dispatcher):
        with patch(
            "spectra_mission.executor.handlers._get_known_tools", return_value={"nmap", "nuclei", "sqlmap"}
        ):
            hint = dispatcher._extract_tool_hint_from_description("Check vulnerabilities with nuclei")
            assert hint == "nuclei"

    def test_extract_tool_hint_no_match(self, dispatcher):
        with patch("spectra_mission.executor.handlers._get_known_tools", return_value={"nmap", "nuclei"}):
            hint = dispatcher._extract_tool_hint_from_description("Analyze the target system")
            assert hint is None

    def test_extract_tool_hint_direct_mention(self, dispatcher):
        with patch(
            "spectra_mission.executor.handlers._get_known_tools", return_value={"nmap", "nuclei", "sqlmap"}
        ):
            hint = dispatcher._extract_tool_hint_from_description("sqlmap injection test")
            assert hint == "sqlmap"


class TestTaskDispatcherDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_known_agent(self):
        tool_service = AsyncMock()
        exploit_manager = AsyncMock()
        consensus = AsyncMock()

        mock_tool_selector = AsyncMock()
        mock_tool_selector.execute = AsyncMock(return_value=MagicMock(success=True, action=MagicMock(actions=[])))
        agents = {"tool_selector": mock_tool_selector}

        dispatcher = TaskDispatcher(tool_service, exploit_manager, consensus, agents)

        # Create minimal mission and task mocks
        mission = MagicMock()
        mission.blackboard = MagicMock()
        mission.blackboard.get_context_for_agent = MagicMock(return_value="")
        mission.task_tree = MagicMock()
        mission.log = MagicMock()

        task = MagicMock()
        task.agent_type = "tool_selector"
        task.task_id = "t1"
        task.phase = MagicMock()
        task.phase.value = "recon"
        task.description = "Run nmap"
        task.parameters = {}

        context = MagicMock()

        # Patch the actual handler to just succeed
        dispatcher._handle_tool_selector = AsyncMock()

        await dispatcher.dispatch(mission, task, context)
        mission.task_tree.update_status.assert_called()

    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent_skips(self):
        dispatcher = TaskDispatcher(AsyncMock(), AsyncMock(), AsyncMock(), {})

        mission = MagicMock()
        mission.blackboard = MagicMock()
        mission.blackboard.get_context_for_agent = MagicMock(return_value="")
        mission.task_tree = MagicMock()
        mission.log = MagicMock()

        task = MagicMock()
        task.agent_type = "totally_unknown_xyz"
        task.task_id = "t1"
        task.phase = MagicMock()
        task.phase.value = "recon"
        task.description = "Unknown task"
        task.parameters = {}

        context = MagicMock()

        await dispatcher.dispatch(mission, task, context)
        mission.log.assert_called()  # Logs "Unknown agent type"
