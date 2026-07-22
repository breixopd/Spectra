"""Shared URL validation utilities (SSRF protection)."""

import asyncio
import ipaddress
import socket
import urllib.parse


def validate_service_endpoint_url(url: str | None) -> str | None:
    """Validate a configured service URL before it can receive credentials.

    Configuration values are allowed to point at Docker service names (for
    example ``http://tensorzero:3000``), but URL credentials, non-HTTP
    schemes, metadata aliases, and literal private addresses are rejected.
    DNS resolution is deliberately performed by callers immediately before a
    request as well; this synchronous check prevents the most common SSRF and
    credential-exfiltration mistakes at the API boundary.
    """
    if url is None or url == "":
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Service endpoint URL must use http or https scheme")
    if parsed.username or parsed.password:
        raise ValueError("Service endpoint URL must not contain embedded credentials")
    if parsed.fragment or not parsed.hostname:
        raise ValueError("Service endpoint URL must include a valid host")

    hostname = parsed.hostname.rstrip(".").lower()
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Bare Docker/Kubernetes service names are expected in the compose
        # topology.  Dotted internal aliases and cloud metadata names are not.
        if hostname in {"localhost", "metadata.google.internal", "metadata", "instance-data"}:
            raise ValueError("Service endpoint URL must not target local or metadata services")
        if hostname.endswith((".local", ".internal", ".localhost")):
            raise ValueError("Service endpoint URL must not target internal DNS names")
    else:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("Service endpoint URL must not target internal/private IP addresses")
    return url


async def is_safe_url(url: str) -> bool:
    """Validate that a URL does not target internal/private networks.

    Returns False for non-HTTP(S) schemes, unresolvable hosts, and
    any address that resolves to a private, loopback, link-local,
    or reserved IP range.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        # Outbound webhooks do not need URL userinfo. Reject embedded
        # credentials before DNS resolution so secrets cannot leak through
        # logs, proxies, or a redirected request.
        if parsed.username or parsed.password:
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        loop = asyncio.get_running_loop()
        addr_info = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
        for info in addr_info:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except (socket.gaierror, ValueError, OSError):
        return False
