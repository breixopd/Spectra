"""Tests for PluginLoader (app/services/tools/registry/loader.py)."""

import json
from unittest.mock import MagicMock

import pytest

from spectra_tools_core.models import RegisteredTool, ToolStatus
from spectra_tools_core.registry.loader import PluginLoader
from spectra_tools_core.registry.validator import PluginValidator


def _minimal_plugin(plugin_id: str = "test-tool", **overrides) -> dict:
    """Build a minimal valid plugin dict."""
    data = {
        "id": plugin_id,
        "name": "Test Tool",
        "version": "1.0.0",
        "category": "discovery",
        "description": "A test tool",
        "execution": {
            "command": "testtool",
            "args_template": "{target}",
        },
    }
    data.update(overrides)
    return data


def _write_plugin(path, filename, data):
    f = path / filename
    f.write_text(json.dumps(data))
    return f


@pytest.mark.asyncio
async def test_load_valid_plugin(tmp_path):
    """Loading a well-formed plugin JSON registers the tool."""
    _write_plugin(tmp_path, "test-tool.json", _minimal_plugin())
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert "test-tool" in tools
    assert isinstance(tools["test-tool"], RegisteredTool)
    assert tools["test-tool"].config.name == "Test Tool"


@pytest.mark.asyncio
async def test_corrupted_json_handled_gracefully(tmp_path):
    """Corrupted JSON should be skipped without crashing."""
    (tmp_path / "bad.json").write_text("{invalid json!!")
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert len(tools) == 0


@pytest.mark.asyncio
async def test_missing_required_fields(tmp_path):
    """Plugin missing required fields should be skipped."""
    incomplete = {"id": "incomplete", "name": "No version"}
    _write_plugin(tmp_path, "incomplete.json", incomplete)
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert "incomplete" not in tools


@pytest.mark.asyncio
async def test_filename_id_mismatch_warning(tmp_path, caplog):
    """Plugin whose ID differs from filename should log a warning."""
    plugin = _minimal_plugin("actual-id")
    _write_plugin(tmp_path, "wrong-name.json", plugin)
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert "actual-id" in tools
    assert any("does not match filename" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_mixed_valid_and_invalid_plugins(tmp_path):
    """Directory with a mix of valid and broken plugins loads what it can."""
    _write_plugin(tmp_path, "good-tool.json", _minimal_plugin("good-tool"))
    (tmp_path / "broken.json").write_text("NOT JSON")
    _write_plugin(tmp_path, "incomplete.json", {"id": "incomplete"})
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert "good-tool" in tools
    assert "broken" not in tools
    assert "incomplete" not in tools


@pytest.mark.asyncio
async def test_empty_plugin_directory(tmp_path):
    """An empty directory should return whatever was already loaded."""
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    tools = await loader.load_plugins({})

    assert tools == {}


@pytest.mark.asyncio
async def test_nonexistent_directory(tmp_path):
    """A directory that doesn't exist should return existing_tools unchanged."""
    missing = tmp_path / "does_not_exist"
    validator = PluginValidator()
    loader = PluginLoader(missing, validator)
    existing = {"kept": "sentinel"}  # type: ignore[dict-item]

    result = await loader.load_plugins(existing)

    assert result is existing


@pytest.mark.asyncio
async def test_removed_plugin_is_pruned(tmp_path):
    """Plugins no longer on disk should be removed from the registry."""
    _write_plugin(tmp_path, "survivor.json", _minimal_plugin("survivor"))
    validator = PluginValidator()
    loader = PluginLoader(tmp_path, validator)

    # Pre-populate with an extra tool that has no file on disk
    fake = MagicMock(spec=RegisteredTool)
    fake.status = ToolStatus.READY
    tools = await loader.load_plugins({"old-tool": fake})

    assert "survivor" in tools
    assert "old-tool" not in tools
