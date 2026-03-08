"""Tests for ChainBuilder and exploit chain functionality."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.services.mission.chain_builder import (
    ChainBuilder,
    ChainStage,
    ExploitChain,
    ChainExecutionResult,
    get_builtin_chains,
    load_custom_chains,
    save_custom_chain,
    BUILTIN_CHAINS,
)


class TestChainStage:
    def test_defaults(self):
        stage = ChainStage(id="s1", name="Scan")
        assert stage.max_retries == 1
        assert stage.timeout == 300
        assert stage.phase == "exploitation"
        assert stage.tool is None
        assert stage.fallback_stage is None

    def test_with_all_fields(self):
        stage = ChainStage(
            id="s1",
            name="SQL Injection",
            tool="sqlmap",
            success_regex="injection|dumped",
            failure_regex="no injection",
            fallback_stage="s2",
            max_retries=3,
        )
        assert stage.tool == "sqlmap"
        assert stage.success_regex == "injection|dumped"


class TestExploitChain:
    def test_empty_chain(self):
        chain = ExploitChain(id="c1", name="Test Chain")
        assert chain.stages == []
        assert chain.metadata == {}

    def test_chain_with_stages(self):
        stages = [
            ChainStage(id="s1", name="Scan", tool="nmap"),
            ChainStage(id="s2", name="Exploit", tool="sqlmap"),
        ]
        chain = ExploitChain(id="c1", name="Web Attack", stages=stages)
        assert len(chain.stages) == 2


class TestChainExecutionResult:
    def test_default_values(self):
        result = ChainExecutionResult(chain_id="c1")
        assert not result.success
        assert result.stages_completed == 0
        assert result.final_access_level == "none"


class TestChainBuilder:
    def test_create_chain(self):
        stages = [
            {"id": "s1", "name": "Scan", "tool": "nmap"},
            {"id": "s2", "name": "Exploit", "tool": "sqlmap"},
        ]
        chain = ChainBuilder.create_chain("Web Attack", stages)
        assert chain.id == "chain-web-attack"
        assert chain.name == "Web Attack"
        assert len(chain.stages) == 2

    def test_validate_chain_valid(self):
        stages = [
            ChainStage(id="s1", name="Scan", tool="nmap"),
            ChainStage(id="s2", name="Exploit", tool="sqlmap", fallback_stage="s1"),
        ]
        chain = ExploitChain(id="c1", name="Test", stages=stages)
        warnings = ChainBuilder.validate_chain(chain)
        assert len(warnings) == 0

    def test_validate_chain_missing_fallback(self):
        stages = [
            ChainStage(id="s1", name="Scan", tool="nmap", fallback_stage="nonexistent"),
        ]
        chain = ExploitChain(id="c1", name="Test", stages=stages)
        warnings = ChainBuilder.validate_chain(chain)
        assert any("nonexistent" in w for w in warnings)

    def test_validate_chain_no_tool_or_description(self):
        stages = [ChainStage(id="s1", name="Empty")]
        chain = ExploitChain(id="c1", name="Test", stages=stages)
        warnings = ChainBuilder.validate_chain(chain)
        assert any("no tool or description" in w for w in warnings)

    def test_validate_empty_chain(self):
        chain = ExploitChain(id="c1", name="Empty")
        warnings = ChainBuilder.validate_chain(chain)
        assert any("no stages" in w for w in warnings)

    def test_check_stage_success_with_regex(self):
        stage = ChainStage(id="s1", name="Scan", success_regex="open")
        assert ChainBuilder.check_stage_success("22/tcp open ssh", stage)
        assert not ChainBuilder.check_stage_success("all ports closed", stage)

    def test_check_stage_success_no_regex(self):
        stage = ChainStage(id="s1", name="Scan")
        assert ChainBuilder.check_stage_success("some output", stage)
        assert not ChainBuilder.check_stage_success("", stage)
        assert not ChainBuilder.check_stage_success("   ", stage)

    def test_check_stage_failure_with_regex(self):
        stage = ChainStage(id="s1", name="Scan", failure_regex="permission denied")
        assert ChainBuilder.check_stage_failure("Error: permission denied", stage)
        assert not ChainBuilder.check_stage_failure("Success!", stage)

    def test_check_stage_failure_no_regex(self):
        stage = ChainStage(id="s1", name="Scan")
        assert not ChainBuilder.check_stage_failure("anything", stage)

    def test_success_regex_case_insensitive(self):
        stage = ChainStage(id="s1", name="Scan", success_regex="OPEN")
        assert ChainBuilder.check_stage_success("22/tcp open ssh", stage)


class TestBuiltinChains:
    def test_builtin_chains_exist(self):
        assert len(BUILTIN_CHAINS) >= 2

    def test_get_builtin_chains(self):
        chains = get_builtin_chains()
        assert len(chains) >= 2
        assert all(isinstance(c, ExploitChain) for c in chains)

    def test_web_to_shell_chain(self):
        chains = get_builtin_chains()
        web_chain = next(c for c in chains if c.id == "chain-web-to-shell")
        assert len(web_chain.stages) == 4
        stage_tools = [s.tool for s in web_chain.stages if s.tool]
        assert "nmap" in stage_tools
        assert "nuclei" in stage_tools

    def test_network_pivot_chain(self):
        chains = get_builtin_chains()
        pivot = next(c for c in chains if c.id == "chain-network-pivot")
        assert len(pivot.stages) == 4


class TestCustomChains:
    def test_load_nonexistent_returns_empty(self):
        with patch("app.services.mission.chain_builder.CUSTOM_CHAINS_PATH", Path("/nonexistent")):
            result = load_custom_chains()
            assert result == []

    def test_load_invalid_json_returns_empty(self, tmp_path):
        bad_file = tmp_path / "chains.json"
        bad_file.write_text("not json")
        with patch("app.services.mission.chain_builder.CUSTOM_CHAINS_PATH", bad_file):
            result = load_custom_chains()
            assert result == []

    def test_save_and_load_custom_chain(self, tmp_path):
        chains_file = tmp_path / "custom_chains.json"
        chain = ExploitChain(
            id="custom-1",
            name="My Chain",
            stages=[ChainStage(id="s1", name="Step1", tool="nmap")],
        )
        with patch("app.services.mission.chain_builder.CUSTOM_CHAINS_PATH", chains_file):
            with patch("app.services.mission.chain_builder.load_custom_chains", return_value=[]):
                save_custom_chain(chain)
            assert chains_file.exists()
            data = json.loads(chains_file.read_text())
            assert len(data) == 1
            assert data[0]["name"] == "My Chain"
