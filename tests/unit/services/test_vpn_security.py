"""Tests for VPN config upload — dangerous directive validation."""

from __future__ import annotations

from spectra_api.api.routers.vpn import DANGEROUS_OPENVPN_DIRECTIVES


class TestDangerousDirectiveDetection:
    """OpenVPN configs with dangerous directives are rejected."""

    def _check_rejected(self, content: str) -> bool:
        """Return True if content would be rejected by the directive check."""
        content_lower = content.lower()
        return any(directive in content_lower for directive in DANGEROUS_OPENVPN_DIRECTIVES)

    def test_rejects_script_security(self):
        config = "client\nscript-security 2\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_rejects_up_directive(self):
        config = "client\nup /etc/openvpn/update.sh\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_rejects_down_directive(self):
        config = "client\ndown /etc/openvpn/teardown.sh\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_rejects_client_connect(self):
        config = "client-connect /tmp/evil.sh\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_rejects_tls_verify(self):
        config = "client\ntls-verify /tmp/check.sh\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_rejects_auth_user_pass_verify(self):
        config = "auth-user-pass-verify /tmp/auth.sh via-file\n"
        assert self._check_rejected(config)

    def test_accepts_clean_openvpn_config(self):
        config = (
            "client\n"
            "dev tun\n"
            "proto udp\n"
            "remote vpn.example.com 1194\n"
            "resolv-retry infinite\n"
            "nobind\n"
            "persist-key\n"
            "persist-tun\n"
            "ca ca.crt\n"
            "cert client.crt\n"
            "key client.key\n"
            "cipher AES-256-GCM\n"
        )
        assert not self._check_rejected(config)

    def test_wireguard_not_checked_for_openvpn_directives(self):
        """WireGuard configs contain different syntax; the OpenVPN directive
        list should not match typical WireGuard content."""
        wg_config = (
            "[Interface]\n"
            "PrivateKey = abc123==\n"
            "Address = 10.0.0.2/24\n"
            "DNS = 1.1.1.1\n"
            "\n"
            "[Peer]\n"
            "PublicKey = xyz789==\n"
            "Endpoint = vpn.example.com:51820\n"
            "AllowedIPs = 0.0.0.0/0\n"
        )
        assert not self._check_rejected(wg_config)

    def test_case_insensitive_detection(self):
        config = "client\nSCRIPT-SECURITY 2\nremote vpn.example.com 1194\n"
        assert self._check_rejected(config)

    def test_all_dangerous_directives_covered(self):
        """Every entry in the DANGEROUS list triggers rejection."""
        for directive in DANGEROUS_OPENVPN_DIRECTIVES:
            config = f"client\n{directive}something\nremote vpn.example.com 1194\n"
            assert self._check_rejected(config), f"Directive '{directive}' not caught"
