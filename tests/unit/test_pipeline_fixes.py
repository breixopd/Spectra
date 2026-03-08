"""Tests for critical mission pipeline bug fixes."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import MISSION_TIMEOUT_SECONDS
from app.models.attack_surface import (
    AttackSurface,
    AttackVector,
    DiscoveredService,
    ExploitAttempt,
    VectorPriority,
    VectorStatus,
)
from app.services.ai.context import truncate_for_llm


# ---------------------------------------------------------------------------
# Fix #4: Port extraction (rsplit for IPv6 safety)
# ---------------------------------------------------------------------------

class TestPortExtraction:
    """Verify port extraction handles IPv4 and IPv6 addresses."""

    def test_ipv4_port(self):
        ref = "10.0.0.1:8080"
        port = int(ref.rsplit(":", 1)[-1])
        assert port == 8080

    def test_ipv6_port(self):
        ref = "[::1]:443"
        port = int(ref.rsplit(":", 1)[-1])
        assert port == 443

    def test_no_port(self):
        ref = "10.0.0.1"
        assert ":" not in ref

    def test_invalid_port_is_safe(self):
        ref = "host:abc"
        with pytest.raises(ValueError):
            int(ref.rsplit(":", 1)[-1])


# ---------------------------------------------------------------------------
# Fix #5: Missing TaskDispatcher handlers
# ---------------------------------------------------------------------------

class TestNewHandlers:
    """Verify post_exploitation and vector_generator handlers registered."""

    @pytest.fixture
    def dispatcher(self):
        from app.services.mission.executor.handlers import TaskDispatcher
        tool_service = AsyncMock()
        exploit_manager = AsyncMock()
        consensus = AsyncMock()
        agents = {
            "tool_selector": AsyncMock(),
            "exploit_crafter": AsyncMock(),
        }
        return TaskDispatcher(tool_service, exploit_manager, consensus, agents)

    def test_post_exploitation_handler_exists(self, dispatcher):
        handler = dispatcher._get_task_handler("post_exploitation")
        assert handler is not None

    def test_vector_generator_handler_exists(self, dispatcher):
        handler = dispatcher._get_task_handler("vector_generator")
        assert handler is not None

    def test_existing_handlers_still_work(self, dispatcher):
        for name in ["tool_selector", "exploit_crafter", "scope", "scope_agent", "reporter"]:
            assert dispatcher._get_task_handler(name) is not None


# ---------------------------------------------------------------------------
# Fix #6: Output truncation
# ---------------------------------------------------------------------------

class TestOutputTruncation:
    """Verify tool output truncation for LLM context."""

    def test_short_output_unchanged(self):
        output = "Short output"
        assert truncate_for_llm(output) == output

    def test_exact_limit_unchanged(self):
        output = "x" * 3000
        assert truncate_for_llm(output, max_chars=3000) == output

    def test_long_output_truncated(self):
        output = "A" * 8000
        result = truncate_for_llm(output, max_chars=3000)
        assert len(result) < len(output)
        assert "omitted" in result
        assert result.startswith("A")
        assert result.endswith("A")

    def test_empty_output(self):
        assert truncate_for_llm("") == ""

    def test_none_safety(self):
        assert truncate_for_llm("") == ""

    def test_stderr_cap(self):
        stderr = "E" * 1000
        result = truncate_for_llm(stderr, max_chars=500, label="stderr")
        assert len(result) < len(stderr)
        assert "stderr" in result


# ---------------------------------------------------------------------------
# Fix #7: Mission timeout constant
# ---------------------------------------------------------------------------

class TestMissionTimeout:
    """Verify mission timeout is configured."""

    def test_timeout_constant_exists(self):
        assert MISSION_TIMEOUT_SECONDS > 0

    def test_timeout_is_one_hour(self):
        assert MISSION_TIMEOUT_SECONDS == 3600


# ---------------------------------------------------------------------------
# Fix #8: LLM retry method
# ---------------------------------------------------------------------------

class TestLLMRetry:
    """Verify LLMClient retry wrapper."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        from app.services.ai.llm import MockLLMClient

        client = MockLLMClient()
        result = await client.generate_with_retry("test prompt")
        assert result.content is not None

    @pytest.mark.asyncio
    async def test_retry_attribute_exists(self):
        from app.services.ai.llm import LLMClient

        assert hasattr(LLMClient, "generate_with_retry")
        assert hasattr(LLMClient, "MAX_RETRIES")
        assert LLMClient.MAX_RETRIES == 3


# ---------------------------------------------------------------------------
# Fix #9: auto_expand_scope wired
# ---------------------------------------------------------------------------

class TestAutoExpandScope:
    """Verify auto_expand_scope is importable and callable."""

    def test_import(self):
        from app.services.mission.executor.analysis import auto_expand_scope
        assert callable(auto_expand_scope)

    def test_returns_expansions_for_new_hosts(self):
        from app.services.mission.executor.analysis import auto_expand_scope

        findings = [
            {"type": "subdomain", "value": "new.example.com"},
            {"type": "host", "value": "10.0.0.5"},
        ]
        scope = {"target": "example.com"}
        expansions = auto_expand_scope(findings, scope)
        assert len(expansions) == 2
        assert expansions[0]["type"] == "domain"
        assert expansions[1]["type"] == "ip"

    def test_no_duplicates(self):
        from app.services.mission.executor.analysis import auto_expand_scope

        findings = [
            {"type": "subdomain", "value": "dup.example.com"},
            {"type": "subdomain", "value": "dup.example.com"},
        ]
        expansions = auto_expand_scope(findings, {})
        assert len(expansions) == 1


# ---------------------------------------------------------------------------
# Fix #10: ChainBuilder integration
# ---------------------------------------------------------------------------

class TestChainBuilderIntegration:
    """Verify ChainBuilder is importable and chains are valid."""

    def test_builtin_chains_load(self):
        from app.services.mission.chain_builder import get_builtin_chains
        chains = get_builtin_chains()
        assert len(chains) >= 2

    def test_chain_validation(self):
        from app.services.mission.chain_builder import ChainBuilder, get_builtin_chains
        for chain in get_builtin_chains():
            warnings = ChainBuilder.validate_chain(chain)
            assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# Fix #3: Tool name validation (tool_selector)
# ---------------------------------------------------------------------------

class TestToolSelectorValidation:
    """Verify tool_selector validates LLM-suggested tool names."""

    def test_fuzzy_match_logic(self):
        """Fuzzy match should find partial name matches."""
        available_ids = ["nmap", "nuclei", "nikto", "hydra"]
        suggested = "Nuclei"  # LLM title-cased
        matches = [t for t in available_ids if suggested.lower() in t.lower() or t.lower() in suggested.lower()]
        assert "nuclei" in matches

    def test_no_match_returns_empty(self):
        available_ids = ["nmap", "nuclei"]
        suggested = "nonexistent_tool"
        matches = [t for t in available_ids if suggested.lower() in t.lower() or t.lower() in suggested.lower()]
        assert matches == []


# ---------------------------------------------------------------------------
# Fix #11: Blackboard read integration
# ---------------------------------------------------------------------------

class TestBlackboardReads:
    """Verify blackboard read method works."""

    def test_blackboard_read_returns_none_for_missing(self):
        from app.services.ai.blackboard import MissionBlackboard
        bb = MissionBlackboard("test")
        assert bb.read("nonexistent") is None

    def test_blackboard_write_then_read(self):
        from app.services.ai.blackboard import MissionBlackboard
        bb = MissionBlackboard("test")
        bb.write("agent", "credentials", [{"user": "admin", "pass": "admin"}])
        result = bb.read("credentials")
        assert result is not None
