"""Credential management for mission-scoped credential reuse."""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

MAX_CREDENTIALS_PER_MISSION = 100

# Patterns to extract credentials from tool output
_HYDRA_PATTERN = re.compile(r"\[(\d+)\]\[(\w+)\]\s+host:\s*(\S+)\s+login:\s*(\S+)\s+password:\s*(\S+)")
_GENERIC_CRED_PATTERN = re.compile(
    r"(?:login|user(?:name)?|account)\s*[:=]\s*(\S+)\s+(?:password|pass|pw)\s*[:=]\s*(\S+)",
    re.IGNORECASE,
)


@dataclass
class Credential:
    """A discovered credential."""

    username: str
    password: str  # or hash
    service: str  # ssh, http, mysql, ftp, etc.
    host: str
    port: int | None = None
    source: str = ""  # How it was found (e.g., "hydra brute-force", "config file leak")
    credential_type: str = "password"  # password, hash, key, token
    verified: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CredentialStore:
    """Mission-scoped credential storage and retrieval."""

    def __init__(self) -> None:
        self._credentials: list[Credential] = []

    def add(self, cred: Credential) -> None:
        """Add a discovered credential, avoiding duplicates."""
        if len(self._credentials) >= MAX_CREDENTIALS_PER_MISSION:
            logger.warning("Credential store full (%d), skipping", MAX_CREDENTIALS_PER_MISSION)
            return

        for existing in self._credentials:
            if (
                existing.username == cred.username
                and existing.password == cred.password
                and existing.host == cred.host
                and existing.service == cred.service
            ):
                if cred.verified:
                    existing.verified = True
                return

        self._credentials.append(cred)
        logger.info(
            "Stored credential: %s@%s:%s (%s)",
            cred.username,
            cred.host,
            cred.service,
            cred.source,
        )

    def get_for_service(self, service: str, host: str | None = None) -> list[Credential]:
        """Get credentials for a specific service, optionally filtered by host."""
        results = [c for c in self._credentials if c.service == service]
        if host:
            results = [c for c in results if c.host == host]
        return results

    def get_for_host(self, host: str) -> list[Credential]:
        """Get all credentials for a host."""
        return [c for c in self._credentials if c.host == host]

    def get_all(self) -> list[Credential]:
        """Get all stored credentials."""
        return list(self._credentials)

    def get_summary_for_prompt(self, host: str | None = None) -> str:
        """Build a compact summary for LLM prompts."""
        creds = self.get_for_host(host) if host else self._credentials
        if not creds:
            return ""
        lines = ["**Discovered Credentials:**"]
        for c in creds[:10]:
            verified = "verified" if c.verified else "unverified"
            lines.append(f"  [{verified}] {c.username}:{c.password} -> {c.service}@{c.host} (via {c.source})")
        if len(creds) > 10:
            lines.append(f"  ... and {len(creds) - 10} more")
        return "\n".join(lines)

    def to_dicts(self) -> list[dict]:
        """Export credentials as plain dicts (for attack_surface.credentials)."""
        return [
            {
                "username": c.username,
                "password": c.password,
                "service": c.service,
                "host": c.host,
                "port": c.port,
                "source": c.source,
                "credential_type": c.credential_type,
                "verified": c.verified,
            }
            for c in self._credentials
        ]

    @property
    def count(self) -> int:
        return len(self._credentials)


def extract_credentials_from_output(
    output: str,
    tool_name: str,
    host: str,
    service: str = "unknown",
) -> list[Credential]:
    """Extract credentials from common tool output formats."""
    found: list[Credential] = []

    # Hydra format: [port][service] host: X   login: Y   password: Z
    for match in _HYDRA_PATTERN.finditer(output):
        port_str, svc, h, user, pw = match.groups()
        found.append(
            Credential(
                username=user,
                password=pw,
                service=svc,
                host=h,
                port=int(port_str),
                source=f"{tool_name} brute-force",
                verified=True,
            )
        )

    # Generic login/password pairs
    if not found:
        for match in _GENERIC_CRED_PATTERN.finditer(output):
            user, pw = match.groups()
            found.append(
                Credential(
                    username=user,
                    password=pw,
                    service=service,
                    host=host,
                    source=tool_name,
                )
            )

    return found
