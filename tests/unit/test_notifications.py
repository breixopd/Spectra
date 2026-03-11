"""Tests for notification SSRF protection."""

from unittest.mock import patch

from app.services.notifications import _is_safe_url


def _fake_addrinfo(ip: str):
    """Create a fake getaddrinfo result for a given IP."""
    return [(None, None, None, None, (ip, 0))]


class TestIsSafeUrl:
    """Tests for _is_safe_url SSRF protection."""

    def test_rejects_localhost(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1")):
            assert _is_safe_url("http://localhost/hook") is False

    def test_rejects_127_0_0_1(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1")):
            assert _is_safe_url("http://127.0.0.1/hook") is False

    def test_rejects_10_x_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("10.0.0.5")):
            assert _is_safe_url("http://internal.corp/hook") is False

    def test_rejects_172_16_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("172.16.0.1")):
            assert _is_safe_url("http://internal.corp/hook") is False

    def test_rejects_192_168_private(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.1")):
            assert _is_safe_url("http://homerouter.local/hook") is False

    def test_rejects_link_local(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("169.254.1.1")):
            assert _is_safe_url("http://whatever/hook") is False

    def test_accepts_valid_external_url(self):
        with patch("app.services.notifications.socket.getaddrinfo", return_value=_fake_addrinfo("1.2.3.4")):
            assert _is_safe_url("https://hooks.slack.com/webhook") is True

    def test_rejects_file_scheme(self):
        assert _is_safe_url("file:///etc/passwd") is False

    def test_rejects_ftp_scheme(self):
        assert _is_safe_url("ftp://evil.com/data") is False

    def test_rejects_empty_string(self):
        assert _is_safe_url("") is False

    def test_handles_malformed_url(self):
        assert _is_safe_url("not a url at all") is False

    def test_handles_dns_failure(self):
        import socket
        with patch("app.services.notifications.socket.getaddrinfo", side_effect=socket.gaierror("no dns")):
            assert _is_safe_url("http://does.not.exist.example/hook") is False

    def test_rejects_url_without_hostname(self):
        assert _is_safe_url("http:///path") is False
