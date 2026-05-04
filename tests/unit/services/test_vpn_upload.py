"""Tests for VPN config directive validation in spectra_api.api.routers.vpn."""

from spectra_api.api.routers.vpn import DANGEROUS_OPENVPN_DIRECTIVES


class TestDangerousDirectiveDetection:
    """Validate that dangerous OpenVPN directives are rejected."""

    def _check_content_rejected(self, content: str) -> bool:
        """Return True if the content contains any dangerous directive."""
        content_lower = content.lower()
        return any(d in content_lower for d in DANGEROUS_OPENVPN_DIRECTIVES)

    def test_rejects_script_security(self):
        config = "client\nremote vpn.example.com 1194\nscript-security 2\n"
        assert self._check_content_rejected(config)

    def test_rejects_up_directive(self):
        config = "client\nremote vpn.example.com 1194\nup /etc/openvpn/update-resolv-conf\n"
        assert self._check_content_rejected(config)

    def test_rejects_down_directive(self):
        config = "client\nremote vpn.example.com 1194\ndown /etc/openvpn/update-resolv-conf\n"
        assert self._check_content_rejected(config)

    def test_rejects_client_connect(self):
        config = "client\nclient-connect /tmp/evil.sh\n"
        assert self._check_content_rejected(config)

    def test_rejects_auth_user_pass_verify(self):
        config = "client\nauth-user-pass-verify /tmp/evil.sh via-env\n"
        assert self._check_content_rejected(config)

    def test_accepts_clean_config(self):
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
        assert not self._check_content_rejected(config)

    def test_directive_list_covers_known_dangerous(self):
        expected = {
            "script-security",
            "up ",
            "down ",
            "client-connect",
            "client-disconnect",
            "tls-verify",
            "ipchange",
            "route-up",
            "route-pre-down",
            "auth-user-pass-verify",
            "learn-address",
        }
        actual = set(DANGEROUS_OPENVPN_DIRECTIVES)
        assert expected.issubset(actual)
