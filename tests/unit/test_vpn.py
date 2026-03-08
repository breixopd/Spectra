"""Unit tests for VPN management service and API."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.vpn import (
    VPNManager,
    _validate_config_name,
    _validate_wireguard_config,
    _validate_openvpn_config,
)


# =============================================================================
# Config name validation
# =============================================================================


class TestConfigNameValidation:
    def test_valid_names(self):
        assert _validate_config_name("my-vpn") == "my-vpn"
        assert _validate_config_name("a") == "a"
        assert _validate_config_name("test123") == "test123"
        assert _validate_config_name("A-B-C") == "A-B-C"
        assert _validate_config_name("x" * 64) == "x" * 64

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            _validate_config_name("")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="1-64 chars"):
            _validate_config_name("x" * 65)

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_config_name("../etc/passwd")

    def test_rejects_special_chars(self):
        for bad in ["my vpn", "my_vpn", "my.vpn", "my/vpn", "my;vpn", "-start"]:
            with pytest.raises(ValueError):
                _validate_config_name(bad)


# =============================================================================
# WireGuard config validation
# =============================================================================


class TestWireGuardValidation:
    def test_valid_config(self):
        config = "[Interface]\nAddress = 10.0.0.2/24\nPrivateKey = abc=\n\n[Peer]\nPublicKey = xyz=\nEndpoint = 1.2.3.4:51820\n"
        _validate_wireguard_config(config)  # Should not raise

    def test_missing_interface(self):
        with pytest.raises(ValueError, match="Interface"):
            _validate_wireguard_config("[Peer]\nPublicKey = xyz=\n")

    def test_missing_peer(self):
        with pytest.raises(ValueError, match="Peer"):
            _validate_wireguard_config("[Interface]\nAddress = 10.0.0.2/24\n")


# =============================================================================
# OpenVPN config validation
# =============================================================================


class TestOpenVPNValidation:
    def test_valid_config(self):
        config = "client\nremote vpn.example.com 1194\ndev tun\nproto udp\n"
        _validate_openvpn_config(config)  # Should not raise

    def test_missing_remote(self):
        with pytest.raises(ValueError, match="remote"):
            _validate_openvpn_config("client\ndev tun\nproto udp\n")

    def test_rejects_up_directive(self):
        with pytest.raises(ValueError, match="forbidden directive.*up"):
            _validate_openvpn_config("remote vpn.example.com 1194\nup /bin/sh\n")

    def test_rejects_down_directive(self):
        with pytest.raises(ValueError, match="forbidden directive.*down"):
            _validate_openvpn_config("remote vpn.example.com 1194\ndown /bin/sh\n")

    def test_rejects_script_security(self):
        with pytest.raises(ValueError, match="forbidden directive.*script-security"):
            _validate_openvpn_config("remote vpn.example.com 1194\nscript-security 2\n")

    def test_rejects_client_connect(self):
        with pytest.raises(ValueError, match="forbidden directive.*client-connect"):
            _validate_openvpn_config("remote vpn.example.com 1194\nclient-connect /tmp/evil.sh\n")

    def test_allows_comments(self):
        config = "# up is fine in comments\nremote vpn.example.com 1194\n"
        _validate_openvpn_config(config)


# =============================================================================
# VPNManager
# =============================================================================


class TestVPNManager:
    @pytest.fixture()
    def tmp_dir(self, tmp_path):
        return tmp_path

    @pytest.fixture()
    def mgr(self, tmp_dir):
        return VPNManager(config_dir=str(tmp_dir))

    @pytest.mark.asyncio
    async def test_upload_wireguard_config(self, mgr, tmp_dir):
        content = b"[Interface]\nAddress = 10.0.0.2/24\nPrivateKey = abc=\n\n[Peer]\nPublicKey = xyz=\nEndpoint = 1.2.3.4:51820\n"
        result = await mgr.upload_config("test-wg", content, "wireguard")
        assert result["name"] == "test-wg"
        assert result["type"] == "wireguard"
        assert (tmp_dir / "test-wg.conf").exists()

    @pytest.mark.asyncio
    async def test_upload_openvpn_config(self, mgr, tmp_dir):
        content = b"client\nremote vpn.example.com 1194\ndev tun\n"
        result = await mgr.upload_config("test-ovpn", content, "openvpn")
        assert result["name"] == "test-ovpn"
        assert result["type"] == "openvpn"
        assert (tmp_dir / "test-ovpn.ovpn").exists()

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_type(self, mgr):
        with pytest.raises(ValueError, match="vpn_type"):
            await mgr.upload_config("name", b"data", "ipsec")

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_name(self, mgr):
        with pytest.raises(ValueError, match="alphanumeric"):
            await mgr.upload_config("../bad", b"[Interface]\n[Peer]\n", "wireguard")

    @pytest.mark.asyncio
    async def test_upload_validates_wireguard(self, mgr):
        with pytest.raises(ValueError, match="Interface"):
            await mgr.upload_config("test", b"invalid content", "wireguard")

    @pytest.mark.asyncio
    async def test_upload_validates_openvpn(self, mgr):
        with pytest.raises(ValueError, match="remote"):
            await mgr.upload_config("test", b"client\ndev tun\n", "openvpn")

    @pytest.mark.asyncio
    async def test_upload_rejects_dangerous_openvpn(self, mgr):
        content = b"remote vpn.example.com 1194\nup /bin/sh\n"
        with pytest.raises(ValueError, match="forbidden"):
            await mgr.upload_config("test", content, "openvpn")

    @pytest.mark.asyncio
    async def test_list_configs_empty(self, mgr):
        configs = await mgr.list_configs()
        assert configs == []

    @pytest.mark.asyncio
    async def test_list_configs(self, mgr, tmp_dir):
        (tmp_dir / "vpn1.conf").write_text("[Interface]\n[Peer]\n")
        (tmp_dir / "vpn2.ovpn").write_text("remote x 1194\n")
        configs = await mgr.list_configs()
        names = {c["name"] for c in configs}
        assert "vpn1" in names
        assert "vpn2" in names

    @pytest.mark.asyncio
    async def test_delete_config(self, mgr, tmp_dir):
        (tmp_dir / "del-me.conf").write_text("[Interface]\n[Peer]\n")
        assert await mgr.delete_config("del-me") is True
        assert not (tmp_dir / "del-me.conf").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, mgr):
        assert await mgr.delete_config("nope") is False

    @pytest.mark.asyncio
    async def test_connect_enqueues_job(self, mgr, tmp_dir):
        (tmp_dir / "myvpn.conf").write_text("[Interface]\n[Peer]\n")
        with patch.object(mgr._queue, "enqueue_job", new_callable=AsyncMock, return_value="job-123"):
            result = await mgr.connect("myvpn")
            assert result["job_id"] == "job-123"
            assert result["action"] == "connect"
            assert result["type"] == "wireguard"

    @pytest.mark.asyncio
    async def test_connect_not_found(self, mgr):
        with pytest.raises(ValueError, match="No config found"):
            await mgr.connect("nonexistent")

    @pytest.mark.asyncio
    async def test_disconnect_enqueues_job(self, mgr, tmp_dir):
        (tmp_dir / "myvpn.ovpn").write_text("remote x 1194\n")
        with patch.object(mgr._queue, "enqueue_job", new_callable=AsyncMock, return_value="job-456"):
            result = await mgr.disconnect("myvpn")
            assert result["job_id"] == "job-456"
            assert result["action"] == "disconnect"

    @pytest.mark.asyncio
    async def test_status_enqueues_job(self, mgr):
        with patch.object(mgr._queue, "enqueue_job", new_callable=AsyncMock, return_value="job-789"):
            result = await mgr.status()
            assert result["job_id"] == "job-789"

    @pytest.mark.asyncio
    async def test_config_file_permissions(self, mgr, tmp_dir):
        content = b"[Interface]\nAddress = 10.0.0.2/24\nPrivateKey = abc=\n\n[Peer]\nPublicKey = xyz=\nEndpoint = 1.2.3.4:51820\n"
        await mgr.upload_config("perm-test", content, "wireguard")
        path = tmp_dir / "perm-test.conf"
        mode = oct(path.stat().st_mode & 0o777)
        assert mode == "0o600"
