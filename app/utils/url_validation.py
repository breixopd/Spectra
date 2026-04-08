"""Shared URL validation utilities (SSRF protection)."""

import ipaddress
import socket
import urllib.parse


def is_safe_url(url: str) -> bool:
    """Validate that a URL does not target internal/private networks.

    Returns False for non-HTTP(S) schemes, unresolvable hosts, and
    any address that resolves to a private, loopback, link-local,
    or reserved IP range.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except (socket.gaierror, ValueError, OSError):
        return False
