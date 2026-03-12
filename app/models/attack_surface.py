"""
Attack Surface Model.

Tracks discovered attack surface components and attack vectors
for iterative exploitation attempts.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


class VectorStatus(StrEnum):
    """Status of an attack vector."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class VectorPriority(StrEnum):
    """Priority levels for attack vectors."""

    CRITICAL = "critical"  # Known RCE, default creds on admin
    HIGH = "high"  # SQLi, authenticated RCE
    MEDIUM = "medium"  # Brute-forceable services, info disclosure
    LOW = "low"  # DOS, complex chains


class DiscoveredService(BaseModel):
    """A discovered service on a host."""

    host: str
    port: int
    protocol: str = "tcp"
    service: str | None = None
    product: str | None = None
    version: str | None = None
    banner: str | None = None
    cpe: str | None = None  # Common Platform Enumeration


class DiscoveredDomain(BaseModel):
    """A discovered domain or subdomain."""

    domain: str
    resolved_ips: list[str] = Field(default_factory=list)
    source: str = "amass"  # Discovery source


class DiscoveredWebApp(BaseModel):
    """A discovered web application."""

    url: str
    technologies: list[str] = Field(default_factory=list)  # WordPress, PHP, nginx
    endpoints: list[str] = Field(default_factory=list)
    forms: list[dict] = Field(default_factory=list)
    authentication: str | None = None  # "basic", "form", "jwt", etc.


class Vulnerability(BaseModel):
    """A discovered vulnerability."""

    id: str
    title: str
    severity: str  # critical, high, medium, low, info
    cve_id: str | None = None
    cvss: float | None = None
    service: DiscoveredService | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    exploitable: bool = True


class ExploitAttempt(BaseModel):
    """Record of a single exploitation attempt."""

    timestamp: datetime = Field(default_factory=_utc_now)
    tool_used: str
    payload: str | None = None
    encoding: str | None = None
    waf_bypass: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)  # Added for storing config

    success: bool
    output: str = ""
    error: str | None = None

    # What we learned
    blocked_by: str | None = None  # "waf", "av", "timeout", "firewall", "rate_limit"
    suggestion: str | None = None  # What to try next


class AttackVector(BaseModel):
    """A potential attack vector to try."""

    id: str
    name: str
    description: str
    priority: VectorPriority
    status: VectorStatus = VectorStatus.PENDING

    # What this vector targets
    target_type: str  # "service", "webapp", "credential", "vulnerability"
    target_ref: str  # Reference to the target (service ID, URL, etc.)

    # Tools/methods to use
    suggested_tools: list[str] = Field(default_factory=list)
    payloads: list[str] = Field(default_factory=list)  # Payload options to try

    # Attempt tracking
    attempts: list[ExploitAttempt] = Field(default_factory=list)
    max_attempts: int = 3

    # Dependencies
    requires_vectors: list[str] = Field(default_factory=list)  # Vector IDs that must succeed first
    chain_id: str | None = None  # ID of the exploit chain this belongs to

    @property
    def can_retry(self) -> bool:
        """Check if this vector can be retried."""
        return self.status == VectorStatus.FAILED and len(self.attempts) < self.max_attempts

    @property
    def attempts_remaining(self) -> int:
        """Number of attempts remaining."""
        return max(0, self.max_attempts - len(self.attempts))


class RetryStrategy(BaseModel):
    """Defines how to retry failed exploitation attempts."""

    # Dynamic strategies - populated by agents/knowledge base
    payload_variations: list[str] = Field(default_factory=list)
    encoding_options: list[str | None] = Field(default_factory=list)
    waf_bypass_techniques: list[str] = Field(default_factory=list)

    def get_next_payload(self, attempt_num: int) -> str | None:
        """Get the next payload to try based on attempt number."""
        if attempt_num < len(self.payload_variations):
            return self.payload_variations[attempt_num]
        return None

    def get_next_encoding(self, attempt_num: int) -> str | None:
        """Get the next encoding to try."""
        if attempt_num < len(self.encoding_options):
            return self.encoding_options[attempt_num]
        return None

    def get_waf_bypass(self, attempt_num: int) -> str | None:
        """Get WAF bypass technique for this attempt."""
        if attempt_num < len(self.waf_bypass_techniques):
            return self.waf_bypass_techniques[attempt_num]
        return None


class AttackSurface(BaseModel):
    """
    Complete attack surface model.

    Tracks all discovered assets and attack vectors.
    """

    # Discovery results
    services: list[DiscoveredService] = Field(default_factory=list)
    domains: list[DiscoveredDomain] = Field(default_factory=list)
    web_apps: list[DiscoveredWebApp] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)

    # Attack vectors (prioritized)
    vectors: list[AttackVector] = Field(default_factory=list)

    # Credentials discovered during testing
    credentials: list[dict] = Field(default_factory=list)

    # Statistics
    exploitation_successes: int = 0
    exploitation_failures: int = 0

    def add_service(self, service: DiscoveredService) -> None:
        """Add a discovered service."""
        # Deduplicate
        key = f"{service.host}:{service.port}"
        existing = [s for s in self.services if f"{s.host}:{s.port}" == key]
        if not existing:
            self.services.append(service)
            # Note: Vector generation is now handled by VectorGeneratorAgent

    def add_vulnerability(self, vuln: Vulnerability) -> None:
        """Add a discovered vulnerability."""
        if vuln.id not in [v.id for v in self.vulnerabilities]:
            self.vulnerabilities.append(vuln)
            # Note: Vector generation is now handled by VectorGeneratorAgent

    def add_web_app(self, app: DiscoveredWebApp) -> None:
        """Add a discovered web application."""
        if app.url not in [a.url for a in self.web_apps]:
            self.web_apps.append(app)
            # Note: Vector generation is now handled by VectorGeneratorAgent

    def add_vector(self, vector: AttackVector) -> None:
        """Add a generated attack vector."""
        if vector.id not in [v.id for v in self.vectors]:
            self.vectors.append(vector)

    # Removed hardcoded _generate_vectors_for_* methods to rely on AI agents

    def get_next_vector(self) -> AttackVector | None:
        """
        Get the next attack vector to try.

        Returns highest priority pending vector whose dependencies are met.
        """
        # Sort by priority
        priority_order = [
            VectorPriority.CRITICAL,
            VectorPriority.HIGH,
            VectorPriority.MEDIUM,
            VectorPriority.LOW,
        ]

        for priority in priority_order:
            for vector in self.vectors:
                if vector.status != VectorStatus.PENDING:
                    continue
                if vector.priority != priority:
                    continue

                # Check dependencies
                deps_met = all(self._vector_succeeded(dep_id) for dep_id in vector.requires_vectors)

                if deps_met:
                    return vector

        return None

    def get_retryable_vectors(self) -> list[AttackVector]:
        """Get vectors that failed but can be retried."""
        return [v for v in self.vectors if v.can_retry]

    def _vector_succeeded(self, vector_id: str) -> bool:
        """Check if a vector has succeeded."""
        for v in self.vectors:
            if v.id == vector_id:
                return v.status == VectorStatus.SUCCESS
        return False

    def mark_vector_started(self, vector_id: str) -> None:
        """Mark a vector as in progress."""
        for v in self.vectors:
            if v.id == vector_id:
                v.status = VectorStatus.IN_PROGRESS
                break

    def record_attempt(self, vector_id: str, attempt: ExploitAttempt) -> None:
        """Record an exploitation attempt."""
        for v in self.vectors:
            if v.id == vector_id:
                v.attempts.append(attempt)

                if attempt.success:
                    v.status = VectorStatus.SUCCESS
                    self.exploitation_successes += 1
                elif len(v.attempts) >= v.max_attempts:
                    v.status = VectorStatus.FAILED
                    self.exploitation_failures += 1
                else:
                    # Can retry
                    v.status = VectorStatus.FAILED
                break

    def get_summary(self) -> dict:
        """Get attack surface summary."""
        # Count vectors by priority
        vectors_by_priority = {
            "critical": len([v for v in self.vectors if v.priority == VectorPriority.CRITICAL]),
            "high": len([v for v in self.vectors if v.priority == VectorPriority.HIGH]),
            "medium": len([v for v in self.vectors if v.priority == VectorPriority.MEDIUM]),
            "low": len([v for v in self.vectors if v.priority == VectorPriority.LOW]),
        }

        return {
            "services": len(self.services),
            "domains": len(self.domains),
            "web_apps": len(self.web_apps),
            "vulnerabilities": len(self.vulnerabilities),
            "vectors_total": len(self.vectors),
            "vectors_pending": len([v for v in self.vectors if v.status == VectorStatus.PENDING]),
            "vectors_success": len([v for v in self.vectors if v.status == VectorStatus.SUCCESS]),
            "vectors_failed": len([v for v in self.vectors if v.status == VectorStatus.FAILED]),
            "vectors_by_priority": vectors_by_priority,
            "exploitation_success_rate": (
                self.exploitation_successes / max(1, self.exploitation_successes + self.exploitation_failures)
            ),
        }

    def prioritize_vectors(self, target_refs: list[str]) -> None:
        """Boost priority of vectors targeting specific refs."""
        for vector in self.vectors:
            if vector.status == VectorStatus.PENDING:
                # Check if vector targets one of the prioritized refs
                if any(ref in vector.target_ref for ref in target_refs):
                    # Boost priority
                    if vector.priority == VectorPriority.LOW:
                        vector.priority = VectorPriority.MEDIUM
                    elif vector.priority == VectorPriority.MEDIUM:
                        vector.priority = VectorPriority.HIGH
                    elif vector.priority == VectorPriority.HIGH:
                        vector.priority = VectorPriority.CRITICAL
