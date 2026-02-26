"""
GeoIP Utility for resolving IP addresses to locations.

Provides IP geolocation using the free ip-api.com service.
"""

import asyncio
import ipaddress
import logging
from typing import TypedDict

import aiohttp

logger = logging.getLogger("spectra.geoip")

# API configuration
GEOIP_API_URL = "https://ipwho.is"
GEOIP_TIMEOUT = 5  # seconds


class GeoLocation(TypedDict):
    """Geographic location data."""

    lat: float
    lon: float
    city: str
    country: str
    region: str | None
    isp: str | None


def _is_private_ip(ip: str) -> bool:
    """
    Check if an IP address is private/local.

    Args:
        ip: IP address string to check.

    Returns:
        True if the IP is private/local, False otherwise.
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved
    except ValueError:
        return False


async def resolve_ip(ip: str) -> GeoLocation | None:
    """
    Resolve an IP address to a geographic location.

    Uses the free ip-api.com service with rate limiting awareness.

    Args:
        ip: IP address string to resolve.

    Returns:
        GeoLocation dict with lat, lon, city, country, or None if resolution fails.
    """
    # Handle localhost and private IPs
    if ip in ["127.0.0.1", "localhost", "::1"] or _is_private_ip(ip):
        return GeoLocation(
            lat=0.0,
            lon=0.0,
            city="Localhost",
            country="Local",
            region=None,
            isp=None,
        )

    # Skip domain names (only resolve IPs)
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.debug("Skipping GeoIP lookup for non-IP: %s", ip)
        return None

    try:
        timeout = aiohttp.ClientTimeout(total=GEOIP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{GEOIP_API_URL}/{ip}") as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("success", False):
                        return GeoLocation(
                            lat=data.get("latitude", 0.0),
                            lon=data.get("longitude", 0.0),
                            city=data.get("city", "Unknown"),
                            country=data.get("country", "Unknown"),
                            region=data.get("region"),
                            isp=data.get("connection", {}).get("isp"),
                        )
                    else:
                        logger.debug("GeoIP lookup failed: %s", data.get("message"))
                elif response.status == 429:
                    logger.warning("GeoIP rate limit exceeded")
                else:
                    logger.warning("GeoIP API returned status %d", response.status)

    except asyncio.TimeoutError:
        logger.warning("GeoIP lookup timed out for %s", ip)
    except aiohttp.ClientError as e:
        logger.warning("GeoIP network error for %s: %s", ip, e)
    except Exception as e:
        logger.warning("GeoIP unexpected error for %s: %s", ip, e)

    return None


async def resolve_batch(
    ips: list[str], delay: float = 0.5
) -> dict[str, GeoLocation | None]:
    """
    Resolve multiple IP addresses with rate limiting.

    Args:
        ips: List of IP addresses to resolve.
        delay: Delay between requests to avoid rate limiting.

    Returns:
        Dictionary mapping IP addresses to their GeoLocation or None.
    """
    results: dict[str, GeoLocation | None] = {}

    for ip in ips:
        results[ip] = await resolve_ip(ip)
        if delay > 0 and ip != ips[-1]:
            await asyncio.sleep(delay)

    return results
