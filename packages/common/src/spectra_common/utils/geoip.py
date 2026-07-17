"""
GeoIP Utility for resolving IP addresses to locations.

Provides IP geolocation using the free ip-api.com service.
"""

import asyncio
import ipaddress
import logging

import aiohttp
from typing_extensions import TypedDict

from spectra_common.constants import GEOIP_API_URL, GEOIP_TIMEOUT

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    """Return a lazily-created, reusable aiohttp session."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=GEOIP_TIMEOUT))
    return _session


async def close_geoip_session() -> None:
    """Close the shared GeoIP HTTP session."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


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
        session = _get_session()
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

    except TimeoutError:
        logger.warning("GeoIP lookup timed out for %s", ip)
    except aiohttp.ClientError as e:
        logger.warning("GeoIP network error for %s: %s", ip, e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("GeoIP unexpected error for %s: %s", ip, e)

    return None


async def resolve_batch(ips: list[str], delay: float = 0.5) -> dict[str, GeoLocation | None]:
    """
    Resolve multiple IP addresses with rate limiting.

    Args:
        ips: List of IP addresses to resolve.
        delay: Delay between requests to avoid rate limiting.

    Returns:
        Dictionary mapping IP addresses to their GeoLocation or None.
    """
    results: dict[str, GeoLocation | None] = {}
    session = _get_session()

    for ip in ips:
        # Handle private/local IPs inline
        if ip in ["127.0.0.1", "localhost", "::1"] or _is_private_ip(ip):
            results[ip] = GeoLocation(
                lat=0.0,
                lon=0.0,
                city="Localhost",
                country="Local",
                region=None,
                isp=None,
            )
            continue

        try:
            ipaddress.ip_address(ip)
        except ValueError:
            logger.debug("Skipping GeoIP lookup for non-IP: %s", ip)
            results[ip] = None
            continue

        try:
            async with session.get(f"{GEOIP_API_URL}/{ip}") as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success", False):
                        results[ip] = GeoLocation(
                            lat=data.get("latitude", 0.0),
                            lon=data.get("longitude", 0.0),
                            city=data.get("city", "Unknown"),
                            country=data.get("country", "Unknown"),
                            region=data.get("region"),
                            isp=data.get("connection", {}).get("isp"),
                        )
                    else:
                        logger.debug("GeoIP lookup failed: %s", data.get("message"))
                        results[ip] = None
                elif response.status == 429:
                    logger.warning("GeoIP rate limit exceeded")
                    results[ip] = None
                else:
                    logger.warning("GeoIP API returned status %d", response.status)
                    results[ip] = None
        except TimeoutError:
            logger.warning("GeoIP lookup timed out for %s", ip)
            results[ip] = None
        except aiohttp.ClientError as e:
            logger.warning("GeoIP network error for %s: %s", ip, e)
            results[ip] = None
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("GeoIP unexpected error for %s: %s", ip, e)
            results[ip] = None

        if delay > 0 and ip != ips[-1]:
            await asyncio.sleep(delay)

    return results
