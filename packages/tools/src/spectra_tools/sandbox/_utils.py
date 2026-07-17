"""Shared utilities for the sandbox subsystem."""

from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.engine import make_url


def sandbox_database_role_name(mission_id: str) -> str:
    """Return the deterministic, safe PostgreSQL role for one mission."""
    try:
        mission_suffix = UUID(mission_id).hex
    except ValueError as exc:
        raise ValueError("Sandbox mission IDs must be UUIDs") from exc
    return f"spectra_sandbox_{mission_suffix}"


def sandbox_database_url(admin_url: str, *, role_name: str, password: str) -> str:
    """Build a URL for one sandbox role without leaking the admin credential."""
    if not password:
        raise ValueError("Sandbox database passwords must not be empty")
    parsed = urlparse(admin_url)
    if not parsed.scheme.startswith("postgresql") or not parsed.hostname:
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL with a host")
    return make_url(admin_url).set(username=role_name, password=password).render_as_string(hide_password=False)
