"""Unit tests for VPN management service and API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from spectra_platform.services.tools.vpn import (
    VPNManager,
    _validate_config_name,
    _validate_openvpn_config,
    _validate_wireguard_config,
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
        assert _validate_config_name("my_vpn") == "my_vpn"
        assert _validate_config_name("u_123e4567-e89b-12d3-a456-426614174000_lab") == "u_123e4567-e89b-12d3-a456-426614174000_lab"
        assert _validate_config_name("x" * 160) == "x" * 160

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            _validate_config_name("")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="1-160 chars"):
            _validate_config_name("x" * 161)

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_config_name("../etc/passwd")
        with pytest.raises(ValueError):
            _validate_config_name("..")

    def test_rejects_special_chars(self):
        for bad in ["my vpn", "my.vpn", "my/vpn", "my;vpn", "-start"]:
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
        with pytest.raises(ValueError, match=r"forbidden directive.*up"):
            _validate_openvpn_config("remote vpn.example.com 1194\nup /bin/sh\n")

    def test_rejects_down_directive(self):
        with pytest.raises(ValueError, match=r"forbidden directive.*down"):
            _validate_openvpn_config("remote vpn.example.com 1194\ndown /bin/sh\n")

    def test_rejects_script_security(self):
        with pytest.raises(ValueError, match=r"forbidden directive.*script-security"):
            _validate_openvpn_config("remote vpn.example.com 1194\nscript-security 2\n")

    def test_rejects_client_connect(self):
        with pytest.raises(ValueError, match=r"forbidden directive.*client-connect"):
            _validate_openvpn_config("remote vpn.example.com 1194\nclient-connect /tmp/evil.sh\n")

    def test_allows_comments(self):
        config = "# up is fine in comments\nremote vpn.example.com 1194\n"
        _validate_openvpn_config(config)


# =============================================================================
# VPNManager (S3-backed)
# =============================================================================


class TestVPNManager:
    @pytest.fixture()
    def tmp_dir(self, tmp_path):
        return tmp_path

    @pytest.fixture()
    def mock_storage(self):
        storage = AsyncMock()
        storage.upload = AsyncMock(return_value="s3://spectra-sessions/vpn/test.conf")
        storage.exists = AsyncMock(return_value=False)
        storage.delete = AsyncMock(return_value=True)
        storage.list_objects = AsyncMock(return_value=[])

        async def _fake_download(bucket, key, dest):
            p = Path(dest)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("placeholder")
            return str(p)

        storage.download_file = AsyncMock(side_effect=_fake_download)
        return storage

    @pytest.fixture(autouse=True)
    def _patch_storage(self, mock_storage):
        with patch("spectra_platform.services.tools.vpn.get_storage_service", return_value=mock_storage):
            yield

    @pytest.fixture()
    def mgr(self, tmp_dir):
        return VPNManager(config_dir=str(tmp_dir))

    @pytest.mark.asyncio
    async def test_upload_wireguard_config(self, mgr, mock_storage):
        content = b"[Interface]\nAddress = 10.0.0.2/24\nPrivateKey = abc=\n\n[Peer]\nPublicKey = xyz=\nEndpoint = 1.2.3.4:51820\n"
        result = await mgr.upload_config("test-wg", content, "wireguard")
        assert result["name"] == "test-wg"
        assert result["type"] == "wireguard"
        mock_storage.upload.assert_called_once()
        call_args = mock_storage.upload.call_args
        assert call_args[0][1] == "vpn/test-wg.conf"
        assert call_args[0][2] == content

    @pytest.mark.asyncio
    async def test_upload_openvpn_config(self, mgr, mock_storage):
        content = b"client\nremote vpn.example.com 1194\ndev tun\n"
        result = await mgr.upload_config("test-ovpn", content, "openvpn")
        assert result["name"] == "test-ovpn"
        assert result["type"] == "openvpn"
        mock_storage.upload.assert_called_once()
        call_args = mock_storage.upload.call_args
        assert call_args[0][1] == "vpn/test-ovpn.ovpn"

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
    async def test_list_configs(self, mgr, mock_storage):
        mock_storage.list_objects = AsyncMock(
            return_value=[
                "vpn/vpn1.conf",
                "vpn/vpn2.ovpn",
            ]
        )
        configs = await mgr.list_configs()
        names = {c["name"] for c in configs}
        assert "vpn1" in names
        assert "vpn2" in names

    @pytest.mark.asyncio
    async def test_delete_config(self, mgr, mock_storage):
        mock_storage.exists = AsyncMock(side_effect=lambda b, k: k.endswith(".conf"))
        assert await mgr.delete_config("del-me") is True
        mock_storage.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, mgr):
        assert await mgr.delete_config("nope") is False

    @pytest.mark.asyncio
    async def test_connect_enqueues_job(self, mgr, mock_storage):
        mock_storage.exists = AsyncMock(side_effect=lambda b, k: k.endswith(".conf"))
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
    async def test_disconnect_enqueues_job(self, mgr, mock_storage):
        mock_storage.exists = AsyncMock(side_effect=lambda b, k: k.endswith(".ovpn"))
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
    async def test_download_sets_permissions(self, mgr, mock_storage, tmp_dir):
        mock_storage.exists = AsyncMock(side_effect=lambda b, k: k.endswith(".conf"))
        path = await mgr._download_to_local("perm-test")
        assert path is not None
        mode = oct(path.stat().st_mode & 0o777)
        assert mode == "0o600"
