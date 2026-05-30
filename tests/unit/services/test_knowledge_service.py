"""
Tests for app.services.ai.knowledge — Knowledge Context Service.

Covers:
- PTES methodology guidance (sync helpers)
- RAG-backed context retrieval (exploit, tool-usage, mission)
- Tool registry context formatting
- Knowledge base indexing
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import spectra_ai_core.knowledge as knowledge_module
from spectra_ai_core.knowledge import (
    PTES_METHODOLOGY,
    close_rag_service,
    get_available_tools_context,
    get_exploit_context,
    get_full_methodology,
    get_methodology_guidance,
    get_mission_context,
    get_tool_usage_context,
    index_exploit_attempt,
)

# ---------------------------------------------------------------------------
# 1. get_methodology_guidance
# ---------------------------------------------------------------------------


class TestGetMethodologyGuidance:
    """Tests for get_methodology_guidance."""

    @pytest.mark.parametrize("phase", list(PTES_METHODOLOGY.keys()))
    def test_known_phase_returns_non_empty(self, phase: str):
        result = get_methodology_guidance(phase)
        assert result, f"Expected non-empty guidance for phase '{phase}'"
        assert result == PTES_METHODOLOGY[phase]

    def test_unknown_phase_returns_fallback(self):
        result = get_methodology_guidance("nonexistent_phase")
        assert result == "Follow standard penetration testing methodology."

    def test_empty_string_phase_returns_fallback(self):
        result = get_methodology_guidance("")
        assert result == "Follow standard penetration testing methodology."


# ---------------------------------------------------------------------------
# 2. get_full_methodology
# ---------------------------------------------------------------------------


class TestGetFullMethodology:
    """Tests for get_full_methodology."""

    def test_returns_string(self):
        result = get_full_methodology()
        assert isinstance(result, str)

    def test_contains_all_phase_names(self):
        result = get_full_methodology()
        for phase in PTES_METHODOLOGY:
            assert phase.title() in result, f"Phase '{phase}' not found in full methodology"

    def test_contains_header(self):
        result = get_full_methodology()
        assert "PTES Methodology" in result

    def test_phases_are_numbered(self):
        result = get_full_methodology()
        for i in range(1, len(PTES_METHODOLOGY) + 1):
            assert f"{i}. " in result


# ---------------------------------------------------------------------------
# Shared RAG mock fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_rag_service():
    """Return an AsyncMock that behaves like RAGService."""
    rag = AsyncMock()
    rag.get_context_for_prompt = AsyncMock(return_value="")
    rag.search = AsyncMock(return_value=[])
    rag.index_document = AsyncMock(return_value=True)
    return rag


# ---------------------------------------------------------------------------
# 3. get_exploit_context
# ---------------------------------------------------------------------------


class TestGetExploitContext:
    """Tests for get_exploit_context (async, RAG-backed)."""

    @pytest.mark.asyncio
    async def test_successful_query_returns_formatted_context(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "CVE-2021-44228 exploit data"

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_exploit_context("log4j exploit", _target="10.0.0.1", max_tokens=500)

        assert "Past Exploits & CVEs" in result
        assert "CVE-2021-44228 exploit data" in result
        mock_rag_service.get_context_for_prompt.assert_awaited_once_with(
            query="log4j exploit",
            max_tokens=500,
            doc_types=["exploit_success", "exploit_failure", "cve"],
        )

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_string(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = ""

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_exploit_context("unknown query")

        assert result == ""

    @pytest.mark.asyncio
    async def test_with_user_id_splits_tenant_and_cve_queries(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt = AsyncMock(side_effect=["tenant-ctx", "cve-ctx"])

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_exploit_context(
                "sqli",
                max_tokens=1000,
                user_id="user-1",
                exclude_session_id="mission-9",
            )

        assert "tenant-ctx" in result
        assert "cve-ctx" in result
        assert mock_rag_service.get_context_for_prompt.await_count == 2
        first = mock_rag_service.get_context_for_prompt.await_args_list[0].kwargs
        second = mock_rag_service.get_context_for_prompt.await_args_list[1].kwargs
        assert first["doc_types"] == ["exploit_success", "exploit_failure"]
        assert first["user_id"] == "user-1"
        assert first["exclude_session_id"] == "mission-9"
        assert second["doc_types"] == ["cve"]
        assert second["user_id"] is None
        assert second["exclude_session_id"] is None


class TestRAGBackendSelection:
    @pytest.mark.asyncio
    async def test_get_rag_service_uses_postgres_backend(self):
        await close_rag_service()
        try:
            with patch("spectra_ai_core.knowledge.RAGService") as mock_postgres_rag:
                mock_instance = AsyncMock()
                mock_postgres_rag.return_value = mock_instance

                rag = await knowledge_module.get_rag_service()

                assert rag is mock_instance
                mock_postgres_rag.assert_called_once_with()
                mock_instance.initialize.assert_awaited_once()
        finally:
            await close_rag_service()

    @pytest.mark.asyncio
    async def test_get_rag_service_returns_singleton_instance(self):
        await close_rag_service()
        try:
            with patch("spectra_ai_core.knowledge.RAGService") as mock_postgres_rag:
                rag_instance = AsyncMock()
                mock_postgres_rag.return_value = rag_instance

                first = await knowledge_module.get_rag_service()
                second = await knowledge_module.get_rag_service()

                assert first is second
                mock_postgres_rag.assert_called_once_with()
                rag_instance.initialize.assert_awaited_once()
        finally:
            await close_rag_service()

    @pytest.mark.asyncio
    async def test_none_result_returns_empty_string(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = None

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_exploit_context("query")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty_string(self):
        with patch(
            "spectra_ai_core.knowledge.get_rag_service",
            side_effect=RuntimeError("Connection failed"),
        ):
            result = await get_exploit_context("query")

        assert result == ""

    @pytest.mark.asyncio
    async def test_rag_method_exception_returns_empty_string(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.side_effect = RuntimeError("search error")

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_exploit_context("query")

        assert result == ""


# ---------------------------------------------------------------------------
# 4. get_tool_usage_context
# ---------------------------------------------------------------------------


class TestGetToolUsageContext:
    """Tests for get_tool_usage_context (async, RAG-backed)."""

    @pytest.mark.asyncio
    async def test_with_services_list(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "nmap scan results"

        services = [
            {"service": "http", "port": 80},
            {"service": "ssh", "port": 22},
        ]

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_tool_usage_context("discovery", services=services)

        assert "Past Successful Actions" in result
        assert "nmap scan results" in result

        call_args = mock_rag_service.get_context_for_prompt.call_args
        query = call_args.kwargs.get("query", call_args.args[0] if call_args.args else "")
        assert "discovery" in query
        assert "http" in query
        assert "ssh" in query

    @pytest.mark.asyncio
    async def test_with_empty_services(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "tool data"

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_tool_usage_context("enumeration", services=[])

        assert "Past Successful Actions" in result
        call_args = mock_rag_service.get_context_for_prompt.call_args
        query = call_args.kwargs.get("query", call_args.args[0] if call_args.args else "")
        assert "enumeration" in query

    @pytest.mark.asyncio
    async def test_with_none_services(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "context"

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_tool_usage_context("exploitation", services=None)

        assert "Past Successful Actions" in result

    @pytest.mark.asyncio
    async def test_empty_rag_result(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = ""

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_tool_usage_context("scope")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty_string(self):
        with patch(
            "spectra_ai_core.knowledge.get_rag_service",
            side_effect=ConnectionError("down"),
        ):
            result = await get_tool_usage_context("discovery")

        assert result == ""

    @pytest.mark.asyncio
    async def test_services_limit_to_three(self, mock_rag_service):
        """Only the first 3 services should appear in the query."""
        mock_rag_service.get_context_for_prompt.return_value = "data"
        services = [
            {"service": "http"},
            {"service": "ssh"},
            {"service": "ftp"},
            {"service": "smtp"},
        ]

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await get_tool_usage_context("discovery", services=services)

        call_args = mock_rag_service.get_context_for_prompt.call_args
        query = call_args.kwargs.get("query", call_args.args[0] if call_args.args else "")
        assert "smtp" not in query

    @pytest.mark.asyncio
    async def test_passes_user_and_exclude_session(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = ""

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await get_tool_usage_context(
                "discovery",
                services=[{"service": "http"}],
                user_id="u-1",
                exclude_session_id="mission-2",
            )

        kwargs = mock_rag_service.get_context_for_prompt.call_args.kwargs
        assert kwargs["user_id"] == "u-1"
        assert kwargs["exclude_session_id"] == "mission-2"


# ---------------------------------------------------------------------------
# 5. get_mission_context
# ---------------------------------------------------------------------------


class TestGetMissionContext:
    """Tests for get_mission_context (async, RAG-backed)."""

    @pytest.mark.asyncio
    async def test_with_target(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "past mission data"

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_mission_context("scan network", target="10.0.0.0/24")

        assert "Past Successful Approaches" in result
        assert "past mission data" in result

        call_args = mock_rag_service.get_context_for_prompt.call_args
        query = call_args.kwargs.get("query", call_args.args[0] if call_args.args else "")
        assert "scan network" in query
        assert "10.0.0.0/24" in query

    @pytest.mark.asyncio
    async def test_passes_user_and_exclude_session_to_rag(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = ""

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await get_mission_context(
                "directive",
                target="t.example",
                user_id="user-1",
                exclude_session_id="mission-99",
            )

        mock_rag_service.get_context_for_prompt.assert_awaited_once()
        kwargs = mock_rag_service.get_context_for_prompt.call_args.kwargs
        assert kwargs["user_id"] == "user-1"
        assert kwargs["exclude_session_id"] == "mission-99"
        assert "mission_summary" in kwargs["doc_types"]
        assert "lesson" in kwargs["doc_types"]

    @pytest.mark.asyncio
    async def test_without_target(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = "context"

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_mission_context("enumerate services", target=None)

        assert "Past Successful Approaches" in result

        call_args = mock_rag_service.get_context_for_prompt.call_args
        query = call_args.kwargs.get("query", call_args.args[0] if call_args.args else "")
        assert "enumerate services" in query

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_string(self, mock_rag_service):
        mock_rag_service.get_context_for_prompt.return_value = ""

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await get_mission_context("directive")

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty_string(self):
        with patch(
            "spectra_ai_core.knowledge.get_rag_service",
            side_effect=RuntimeError("fail"),
        ):
            result = await get_mission_context("directive", target="host")

        assert result == ""


# ---------------------------------------------------------------------------
# 6. get_available_tools_context
# ---------------------------------------------------------------------------


def _make_mock_tool(
    name: str,
    tool_id: str,
    category: str,
    available: bool,
    description: str = "A tool",
    capabilities=None,
):
    """Helper to create a mock RegisteredTool."""
    tool = MagicMock()
    tool.config.name = name
    tool.config.id = tool_id
    tool.config.category = category
    tool.config.description = description
    tool.is_available = available

    if capabilities is None:
        cap = MagicMock()
        cap.value = "port_scan"
        capabilities = [cap]
    tool.config.metadata.capabilities = capabilities
    return tool


class TestGetAvailableToolsContext:
    """Tests for get_available_tools_context (async, tool-registry-backed)."""

    @pytest.mark.asyncio
    async def test_grouped_mode(self):
        tools = [
            _make_mock_tool("Nmap", "nmap", "scanner", True),
            _make_mock_tool("Nikto", "nikto", "scanner", False),
            _make_mock_tool("SQLMap", "sqlmap", "exploitation", True),
        ]

        mock_registry = MagicMock()
        mock_registry.sync_status_from_cache = AsyncMock()
        mock_registry.list_tools.return_value = tools

        with patch("spectra_tools_core.registry.get_registry", return_value=mock_registry):
            result = await get_available_tools_context(grouped=True)

        assert "Available Security Tools" in result
        assert "scanner" in result
        assert "exploitation" in result
        assert "Nmap" in result
        assert "[ready]" in result
        assert "[pending]" in result

    @pytest.mark.asyncio
    async def test_detailed_mode(self):
        cap = MagicMock()
        cap.value = "port_scan"
        tools = [
            _make_mock_tool(
                "Nmap",
                "nmap",
                "scanner",
                True,
                description="Network mapper for host discovery and service detection",
                capabilities=[cap],
            ),
        ]

        mock_registry = MagicMock()
        mock_registry.sync_status_from_cache = AsyncMock()
        mock_registry.list_tools.return_value = tools

        with patch("spectra_tools_core.registry.get_registry", return_value=mock_registry):
            result = await get_available_tools_context(grouped=False)

        assert "Security Tools" in result
        assert "Nmap" in result
        assert "installed" in result
        assert "port_scan" in result

    @pytest.mark.asyncio
    async def test_detailed_mode_pending_tool(self):
        cap = MagicMock()
        cap.value = "vuln_scan"
        tools = [
            _make_mock_tool(
                "Nikto",
                "nikto",
                "scanner",
                False,
                description="Web server scanner",
                capabilities=[cap],
            ),
        ]

        mock_registry = MagicMock()
        mock_registry.sync_status_from_cache = AsyncMock()
        mock_registry.list_tools.return_value = tools

        with patch("spectra_tools_core.registry.get_registry", return_value=mock_registry):
            result = await get_available_tools_context(grouped=False)

        assert "auto-install" in result

    @pytest.mark.asyncio
    async def test_empty_registry(self):
        mock_registry = MagicMock()
        mock_registry.sync_status_from_cache = AsyncMock()
        mock_registry.list_tools.return_value = []

        with patch("spectra_tools_core.registry.get_registry", return_value=mock_registry):
            result = await get_available_tools_context(grouped=True)

        assert result == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty_string(self):
        with patch(
            "spectra_tools_core.registry.get_registry",
            side_effect=ImportError("no module"),
        ):
            result = await get_available_tools_context()

        assert result == ""

    @pytest.mark.asyncio
    async def test_sync_status_failure_still_returns_tools(self):
        """If sync_status_from_cache fails, tools should still be listed."""
        tools = [_make_mock_tool("Nmap", "nmap", "scanner", True)]

        mock_registry = MagicMock()
        mock_registry.sync_status_from_cache = AsyncMock(side_effect=RuntimeError("cache down"))
        mock_registry.list_tools.return_value = tools

        with patch("spectra_tools_core.registry.get_registry", return_value=mock_registry):
            result = await get_available_tools_context(grouped=True)

        assert "Nmap" in result


# ---------------------------------------------------------------------------
# 7. index_exploit_attempt
# ---------------------------------------------------------------------------


class TestIndexExploitAttempt:
    """Tests for index_exploit_attempt (async, RAG-backed)."""

    @pytest.mark.asyncio
    async def test_successful_indexing(self, mock_rag_service):
        mock_rag_service.index_document.return_value = True

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await index_exploit_attempt(
                vector_name="SQL Injection on login",
                vector_type="exploit",
                target_ref="http://target/login",
                tool_used="sqlmap",
                payload="' OR 1=1 --",
                success=True,
                output="Database dumped",
                error=None,
                blocked_by=None,
                priority="high",
                mission_id="mission-123",
                target="10.0.0.1",
            )

        assert result is True
        mock_rag_service.index_document.assert_awaited_once()

        doc_arg = mock_rag_service.index_document.call_args[0][0]
        assert doc_arg.doc_type == "exploit_success"
        assert doc_arg.target == "10.0.0.1"
        assert doc_arg.session_id == "mission-123"
        assert "SQL-Injection" in doc_arg.id

    @pytest.mark.asyncio
    async def test_failed_exploit_uses_failure_doc_type(self, mock_rag_service):
        mock_rag_service.index_document.return_value = True

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await index_exploit_attempt(
                vector_name="XSS attempt",
                vector_type="exploit",
                target_ref="http://target/search",
                tool_used="xsstrike",
                payload="<script>alert(1)</script>",
                success=False,
                output="Blocked by WAF",
                error="WAF detected",
                blocked_by="ModSecurity",
                priority="medium",
                mission_id="mission-456",
                target="10.0.0.2",
            )

        assert result is True
        doc_arg = mock_rag_service.index_document.call_args[0][0]
        assert doc_arg.doc_type == "exploit_failure"

    @pytest.mark.asyncio
    async def test_failure_returns_false(self):
        with patch(
            "spectra_ai_core.knowledge.get_rag_service",
            side_effect=RuntimeError("connection refused"),
        ):
            result = await index_exploit_attempt(
                vector_name="test",
                vector_type="exploit",
                target_ref="ref",
                tool_used="tool",
                payload=None,
                success=True,
                output="out",
                error=None,
                blocked_by=None,
                priority="low",
                mission_id="m-1",
                target="host",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_index_document_exception_returns_false(self, mock_rag_service):
        mock_rag_service.index_document.side_effect = RuntimeError("write error")

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            result = await index_exploit_attempt(
                vector_name="test",
                vector_type="exploit",
                target_ref="ref",
                tool_used="tool",
                payload=None,
                success=True,
                output="out",
                error=None,
                blocked_by=None,
                priority="low",
                mission_id="m-1",
                target="host",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_output_truncated_to_500_chars(self, mock_rag_service):
        mock_rag_service.index_document.return_value = True
        long_output = "x" * 1000

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await index_exploit_attempt(
                vector_name="test",
                vector_type="exploit",
                target_ref="ref",
                tool_used="tool",
                payload=None,
                success=True,
                output=long_output,
                error=None,
                blocked_by=None,
                priority="low",
                mission_id="m-1",
                target="host",
            )

        import json

        doc_arg = mock_rag_service.index_document.call_args[0][0]
        content = json.loads(doc_arg.content)
        assert len(content["output_summary"]) == 500

    @pytest.mark.asyncio
    async def test_document_metadata_contains_tool_and_mission(self, mock_rag_service):
        mock_rag_service.index_document.return_value = True

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await index_exploit_attempt(
                vector_name="test",
                vector_type="exploit",
                target_ref="ref",
                tool_used="nmap",
                payload=None,
                success=True,
                output="ok",
                error=None,
                blocked_by=None,
                priority="low",
                mission_id="m-42",
                target="host",
            )

        doc_arg = mock_rag_service.index_document.call_args[0][0]
        assert doc_arg.metadata["tool"] == "nmap"
        assert doc_arg.metadata["mission_id"] == "m-42"
        assert doc_arg.metadata["success"] is True
        assert "user_id" not in doc_arg.metadata

    @pytest.mark.asyncio
    async def test_user_id_in_metadata_when_passed(self, mock_rag_service):
        mock_rag_service.index_document.return_value = True

        with patch("spectra_ai_core.knowledge.get_rag_service", return_value=mock_rag_service):
            await index_exploit_attempt(
                vector_name="test",
                vector_type="exploit",
                target_ref="ref",
                tool_used="nmap",
                payload=None,
                success=True,
                output="ok",
                error=None,
                blocked_by=None,
                priority="low",
                mission_id="m-42",
                target="host",
                user_id="owner-uuid",
            )

        doc_arg = mock_rag_service.index_document.call_args[0][0]
        assert doc_arg.metadata["user_id"] == "owner-uuid"
