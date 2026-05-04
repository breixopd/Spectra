"""Tests for CommandBuilder (app/services/tools/adapter/builder.py)."""

import shlex

import pytest

from spectra_tools_core.adapter.builder import CommandBuilder
from spectra_tools_core.models import (
    ExecutionConfig,
    ToolCategory,
    ToolConfig,
    ToolExecutionRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_config(
    command="nmap",
    args_template="{target}",
    arg_modifiers=None,
    tool_id="test-tool",
):
    """Build a real ToolConfig Pydantic model for builder tests."""
    return ToolConfig(
        id=tool_id,
        name="Test Tool",
        version="1.0.0",
        category=ToolCategory.DISCOVERY,
        description="A test tool",
        execution=ExecutionConfig(
            command=command,
            args_template=args_template,
            arg_modifiers=arg_modifiers or {},
        ),
    )


def _make_request(target="192.168.1.1", args=None, tool_id="test-tool"):
    return ToolExecutionRequest(
        tool_id=tool_id,
        target=target,
        args=args or {},
    )


# =====================================================================
# Basic command building
# =====================================================================


class TestBuildCommandBasic:
    def test_basic_target_substitution(self):
        config = _make_tool_config(command="nmap", args_template="-sV {target}")
        builder = CommandBuilder(config)
        request = _make_request(target="10.0.0.1")

        cmd = builder.build_command(request)

        assert cmd.startswith("nmap")
        assert "10.0.0.1" in cmd

    def test_multiple_placeholder_substitution(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} --port {port} --proto {proto}",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="example.com", args={"port": "443", "proto": "tcp"})

        cmd = builder.build_command(request)

        assert "example.com" in cmd
        assert "443" in cmd
        assert "tcp" in cmd

    def test_leftover_placeholders_removed(self):
        config = _make_tool_config(command="scan", args_template="{target} {flags} {options}")
        builder = CommandBuilder(config)
        request = _make_request(target="host.com")

        cmd = builder.build_command(request)

        assert "{flags}" not in cmd
        assert "{options}" not in cmd
        assert "host.com" in cmd

    def test_extra_spaces_collapsed(self):
        config = _make_tool_config(command="tool", args_template="{target}  {unused}  {also_unused}")
        builder = CommandBuilder(config)
        request = _make_request(target="host")

        cmd = builder.build_command(request)
        assert "  " not in cmd


# =====================================================================
# Output file placeholder
# =====================================================================


class TestOutputFilePlaceholder:
    def test_output_file_with_dir(self, tmp_path):
        config = _make_tool_config(
            command="nmap",
            args_template="-sV {target} -oX {output_file}",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="10.0.0.1")

        cmd = builder.build_command(request, output_dir=str(tmp_path))

        assert "test-tool_output" in cmd
        assert str(tmp_path) in cmd

    def test_output_file_without_dir_raises(self):
        config = _make_tool_config(
            command="nmap",
            args_template="-sV {target} -oX {output_file}",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="10.0.0.1")

        with pytest.raises(ValueError, match="requires output_dir"):
            builder.build_command(request)

    def test_no_output_file_placeholder(self):
        config = _make_tool_config(command="tool", args_template="-t {target}")
        builder = CommandBuilder(config)
        request = _make_request(target="host")

        cmd = builder.build_command(request)
        assert "output_file" not in cmd


# =====================================================================
# Arg modifiers
# =====================================================================


class TestArgModifiers:
    def test_prefix_applied(self):
        config = _make_tool_config(
            command="nuclei",
            args_template="-target {target} {tags}",
            arg_modifiers={"tags": {"prefix": "-tags "}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="example.com", args={"tags": "cves"})

        cmd = builder.build_command(request)
        assert "-tags" in cmd
        assert "cves" in cmd

    def test_separator_applied(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} {extensions}",
            arg_modifiers={"extensions": {"prefix": "-x ", "separator": ","}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"extensions": "php html txt"})

        cmd = builder.build_command(request)
        assert "php,html,txt" in cmd

    def test_empty_arg_removed(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} {tags}",
            arg_modifiers={"tags": {"prefix": "-t "}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"tags": ""})

        cmd = builder.build_command(request)
        assert "-t" not in cmd

    def test_none_value_arg_placeholder_removed(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} {tags}",
            arg_modifiers={"tags": {"prefix": "-t "}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"tags": "None"})

        cmd = builder.build_command(request)
        assert "-t" not in cmd

    def test_duplicate_prefix_stripped(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} {tags}",
            arg_modifiers={"tags": {"prefix": "-t "}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"tags": "-t cves"})

        cmd = builder.build_command(request)
        parts = cmd.split()
        assert parts.count("-t") == 1

    def test_no_modifiers_passthrough(self):
        config = _make_tool_config(command="tool", args_template="{target} {extra}")
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"extra": "value"})

        cmd = builder.build_command(request)
        assert "value" in cmd


# =====================================================================
# Conditional blocks
# =====================================================================


class TestConditionalBlocks:
    def test_present_placeholder_keeps_block(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} [-p {port}]",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"port": "80"})

        cmd = builder.build_command(request)
        assert "80" in cmd

    def test_missing_placeholder_removes_block(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} [-p {port}]",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host")

        cmd = builder.build_command(request)
        assert "-p" not in cmd
        assert "[" not in cmd
        assert "]" not in cmd

    def test_multiple_conditional_blocks(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} [-p {port}] [--rate {rate}]",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"port": "443"})

        cmd = builder.build_command(request)
        assert "443" in cmd
        assert "--rate" not in cmd

    def test_conditional_with_empty_value_removes_block(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} [-p {port}]",
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"port": ""})

        cmd = builder.build_command(request)
        assert "-p" not in cmd


# =====================================================================
# Shell injection prevention
# =====================================================================


class TestShellInjectionPrevention:
    def test_special_chars_quoted(self):
        config = _make_tool_config(command="tool", args_template="{target}")
        builder = CommandBuilder(config)
        request = _make_request(target="$(whoami)")

        cmd = builder.build_command(request)
        assert "$(whoami)" not in cmd or shlex.quote("$(whoami)") in cmd

    def test_semicolon_injection_quoted(self):
        config = _make_tool_config(command="tool", args_template="{target}")
        builder = CommandBuilder(config)
        request = _make_request(target="host; rm -rf /")

        cmd = builder.build_command(request)
        assert cmd.count("tool") == 1
        quoted = shlex.quote("host; rm -rf /")
        assert quoted in cmd

    def test_backtick_injection_quoted(self):
        config = _make_tool_config(command="tool", args_template="{target}")
        builder = CommandBuilder(config)
        request = _make_request(target="`cat /etc/passwd`")

        cmd = builder.build_command(request)
        assert shlex.quote("`cat /etc/passwd`") in cmd

    def test_pipe_injection_quoted(self):
        config = _make_tool_config(command="tool", args_template="{target}")
        builder = CommandBuilder(config)
        request = _make_request(target="host | cat /etc/shadow")

        cmd = builder.build_command(request)
        quoted = shlex.quote("host | cat /etc/shadow")
        assert quoted in cmd

    @pytest.mark.parametrize(
        "payload",
        [
            "192.168.1.1; id",
            "host$(id)",
            "host`id`",
            "host|id",
            "host&false",
            "host>out",
            "host<in",
            "host'q",
            'host"d',
        ],
    )
    def test_target_metachar_variants_quoted(self, payload: str):
        """Regression: user-supplied targets must appear only via shlex.quote."""
        config = _make_tool_config(command="nmap", args_template="-sV {target}")
        builder = CommandBuilder(config)
        request = _make_request(target=payload)

        cmd = builder.build_command(request)
        assert shlex.quote(payload) in cmd

    def test_newline_in_target_collapsed_to_space_inside_command(self):
        """Whitespace collapse runs on the full args string after quoting."""
        config = _make_tool_config(command="nmap", args_template="-sV {target}")
        builder = CommandBuilder(config)
        request = _make_request(target="host\nid")

        cmd = builder.build_command(request)
        assert "nmap -sV" in cmd
        assert "host" in cmd and "id" in cmd
        assert "\n" not in cmd


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    def test_target_cannot_be_overridden_by_args(self):
        config = _make_tool_config(command="tool", args_template="{target}")
        builder = CommandBuilder(config)
        request = _make_request(target="safe-host", args={"target": "evil-host"})

        cmd = builder.build_command(request)
        assert "safe-host" in cmd

    def test_empty_args_template(self):
        config = _make_tool_config(command="tool", args_template="")
        builder = CommandBuilder(config)
        request = _make_request(target="host")

        cmd = builder.build_command(request)
        assert cmd == "tool"

    def test_flag_with_space_value_split(self):
        config = _make_tool_config(
            command="tool",
            args_template="{target} {opts}",
            arg_modifiers={"opts": {"prefix": "-x "}},
        )
        builder = CommandBuilder(config)
        request = _make_request(target="host", args={"opts": "a,b,c"})

        cmd = builder.build_command(request)
        assert "-x" in cmd
        assert "a,b,c" in cmd
