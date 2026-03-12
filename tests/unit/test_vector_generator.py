"""Tests for VectorGeneratorAgent deterministic and LLM vector generation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.vector_generator import (
    VectorGeneratorAgent,
    VectorGeneratorInput,
)


class TestDeterministicVectors:
    def test_http_service_generates_web_vectors(self):
        services = {80: "http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "Directory Brute Force" in names
        assert "Web Vulnerability Scan" in names
        assert "SQL Injection" in names
        assert "CMS Detection + Exploitation" in names

    def test_smb_service_generates_smb_vectors(self):
        services = {445: "microsoft-ds smb"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "SMB Enumeration" in names
        assert "EternalBlue Check" in names
        assert "SMB Brute Force" in names

    def test_ssh_vectors(self):
        services = {22: "ssh"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "SSH Version Check" in names
        assert "SSH Brute Force" in names

    def test_ftp_vectors(self):
        services = {21: "ftp"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "Anonymous FTP Check" in names
        assert "FTP Version Exploit" in names

    def test_mysql_vectors(self):
        services = {3306: "mysql"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "MySQL Brute Force" in names
        assert "MySQL Enumeration" in names

    def test_dns_vectors(self):
        services = {53: "dns"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "DNS Zone Transfer" in names
        assert "Subdomain Enumeration" in names

    def test_mixed_services_combined(self):
        services = {80: "http", 22: "ssh", 445: "smb"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        names = [v["name"] for v in vectors]
        assert "Directory Brute Force" in names
        assert "SSH Brute Force" in names
        assert "SMB Enumeration" in names

    def test_unknown_service_empty(self):
        services = {9999: "custom_unknown"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        assert vectors == []

    def test_empty_services(self):
        vectors = VectorGeneratorAgent.generate_deterministic_vectors({})
        assert vectors == []

    def test_vectors_have_target_port(self):
        services = {8080: "http-alt http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        for v in vectors:
            assert v["target_port"] == 8080

    def test_vectors_have_target_service(self):
        services = {22: "ssh"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        for v in vectors:
            assert v["target_service"] == "ssh"

    def test_vectors_have_tools(self):
        services = {80: "http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        for v in vectors:
            assert "tools" in v
            assert len(v["tools"]) > 0

    def test_vectors_have_phase(self):
        services = {80: "http"}
        vectors = VectorGeneratorAgent.generate_deterministic_vectors(services)
        valid_phases = {"recon", "vuln_scan", "exploitation"}
        for v in vectors:
            assert v["phase"] in valid_phases


class TestVectorGeneratorInput:
    def test_input_creation(self):
        inp = VectorGeneratorInput(
            target_type="service",
            target_data={"port": 80, "service": "http"},
        )
        assert inp.target_type == "service"
        assert inp.context_notes is None

    def test_input_with_context(self):
        inp = VectorGeneratorInput(
            target_type="webapp",
            target_data={"url": "http://target.local"},
            context_notes="WordPress detected",
        )
        assert inp.context_notes == "WordPress detected"


class TestVectorGeneratorAgent:
    @pytest.mark.asyncio
    async def test_execute_with_deterministic_vectors(self):
        mock_llm = AsyncMock()
        mock_llm.generate_structured = AsyncMock(
            return_value=MagicMock(vectors=[], confidence=0.8, risk_level="low", reasoning="test")
        )
        agent = VectorGeneratorAgent(mock_llm)

        context = AgentContext(
            mission_id="m-test",
            target="192.168.1.1",
            session_id="test-session",
        )
        input_data = VectorGeneratorInput(
            target_type="service",
            target_data={"port": 80, "service": "http", "host": "192.168.1.1"},
        )

        with patch("app.services.ai.knowledge.get_exploit_context", new_callable=AsyncMock, return_value=""):
            with patch(
                "app.services.ai.knowledge.get_available_tools_context", new_callable=AsyncMock, return_value=""
            ):
                result = await agent.execute(context, input_data)

        assert result.success
        # Should have deterministic vectors for HTTP
        assert len(result.action.vectors) > 0

    @pytest.mark.asyncio
    async def test_execute_unknown_service_falls_through_to_llm(self):
        mock_llm = AsyncMock()
        mock_llm.generate_structured = AsyncMock(
            return_value=MagicMock(vectors=[], confidence=0.5, risk_level="low", reasoning="")
        )
        agent = VectorGeneratorAgent(mock_llm)

        context = AgentContext(
            mission_id="m-test",
            target="192.168.1.1",
            session_id="test-session",
        )
        input_data = VectorGeneratorInput(
            target_type="service",
            target_data={"port": 9999, "service": "custom", "host": "192.168.1.1"},
        )

        with patch("app.services.ai.knowledge.get_exploit_context", new_callable=AsyncMock, return_value=""):
            with patch(
                "app.services.ai.knowledge.get_available_tools_context", new_callable=AsyncMock, return_value=""
            ):
                result = await agent.execute(context, input_data)

        assert result.success

    @pytest.mark.asyncio
    async def test_execute_handles_llm_error_gracefully(self):
        mock_llm = AsyncMock()
        mock_llm.generate_structured = AsyncMock(side_effect=Exception("LLM down"))
        agent = VectorGeneratorAgent(mock_llm)

        context = AgentContext(
            mission_id="m-test",
            target="192.168.1.1",
            session_id="test",
        )
        input_data = VectorGeneratorInput(
            target_type="service",
            target_data={"port": 80, "service": "http", "host": "192.168.1.1"},
        )

        with patch("app.services.ai.knowledge.get_exploit_context", new_callable=AsyncMock, return_value=""):
            with patch(
                "app.services.ai.knowledge.get_available_tools_context", new_callable=AsyncMock, return_value=""
            ):
                result = await agent.execute(context, input_data)

        # LLM error is caught in _generate_with_llm, deterministic vectors still returned
        assert result.success
        assert len(result.action.vectors) > 0  # Deterministic HTTP vectors
