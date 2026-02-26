"""Tests for plugin signature verification and safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.tools.registry import (
    PluginSignatureError,
    PluginValidationError,
    ToolRegistry,
)


@pytest.fixture
def keys(tmp_path):
    """Generate temporary keys for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_path = tmp_path / "test.pem"
    pub_path = tmp_path / "test.pub"

    with open(priv_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open(pub_path, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    return priv_path, pub_path


@pytest.fixture
def registry(tmp_path, keys):
    """Create a registry instance with safe mode enabled."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    return ToolRegistry(
        plugins_dir=plugins_dir, public_key_path=keys[1], safe_mode=True
    )


def sign_data(data: dict, key_path: Path) -> str:
    """Sign data dictionary."""
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError(f"Expected Ed25519 private key, got {type(private_key)}")

    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )

    return private_key.sign(canonical_json).hex()


@pytest.mark.asyncio
async def test_valid_signature(registry, keys):
    """Test loading a plugin with a valid signature."""
    plugin_data = {
        "id": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {"command": "echo", "args_template": "{target}", "timeout": 5},
        "installation": {"method": "none", "commands": []},
    }

    # Sign
    plugin_data["signature"] = sign_data(plugin_data, keys[0])

    # Validate
    config = registry.validate_plugin(plugin_data)
    assert config.id == "test-tool"


@pytest.mark.asyncio
async def test_invalid_signature(registry, keys):
    """Test loading a plugin with an invalid signature."""
    plugin_data = {
        "id": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {"command": "echo", "args_template": "{target}", "timeout": 5},
        "installation": {"method": "none", "commands": []},
    }

    # Sign then tamper
    plugin_data["signature"] = sign_data(plugin_data, keys[0])
    plugin_data["description"] = "Tampered description"

    with pytest.raises(PluginSignatureError):
        registry.validate_plugin(plugin_data)


@pytest.mark.asyncio
async def test_missing_signature_safe_mode(registry):
    """Test loading an unsigned plugin in safe mode."""
    plugin_data = {
        "id": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {"command": "echo", "args_template": "{target}", "timeout": 5},
        "installation": {"method": "none", "commands": []},
    }

    with pytest.raises(PluginSignatureError):
        registry.validate_plugin(plugin_data)


@pytest.mark.asyncio
async def test_dangerous_command(registry, keys):
    """Test loading a plugin with dangerous commands."""
    plugin_data = {
        "id": "evil-tool",
        "name": "Evil Tool",
        "description": "A test tool",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {"command": "echo", "args_template": "{target}", "timeout": 5},
        "installation": {"method": "script", "commands": ["rm -rf /"]},
    }

    # Sign (even signed dangerous plugins should be rejected)
    plugin_data["signature"] = sign_data(plugin_data, keys[0])

    with pytest.raises(PluginValidationError, match="Dangerous command"):
        registry.validate_plugin(plugin_data)
