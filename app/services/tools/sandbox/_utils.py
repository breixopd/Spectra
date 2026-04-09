"""Shared utilities for the sandbox subsystem."""

from urllib.parse import urlparse, urlunparse


def sandbox_database_url(raw_url: str) -> str:
    """Rewrite compose-only host aliases to names resolvable by ad hoc sandboxes."""
    parsed = urlparse(raw_url)
    if parsed.hostname != "db":
        return raw_url
    netloc = parsed.netloc.replace("@db:", "@spectra-db:").replace("//db:", "//spectra-db:")
    if parsed.netloc.endswith("@db"):
        netloc = netloc[:-3] + "spectra-db"
    return urlunparse(parsed._replace(netloc=netloc))
