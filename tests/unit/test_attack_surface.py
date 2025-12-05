"""
Tests for the Attack Surface model and tracking.
"""

import pytest
from datetime import datetime

from app.models.attack_surface import (
    AttackSurface,
    AttackVector,
    VectorPriority,
    VectorStatus,
    DiscoveredService,
    DiscoveredWebApp,
    Vulnerability,
    ExploitAttempt,
    RetryStrategy,
)


class TestDiscoveredService:
    """Tests for DiscoveredService model."""

    def test_create_basic_service(self):
        """Create a basic service discovery."""
        service = DiscoveredService(
            host="192.168.1.1",
            port=22,
            service="ssh",
        )

        assert service.host == "192.168.1.1"
        assert service.port == 22
        assert service.service == "ssh"
        assert service.protocol == "tcp"  # default

    def test_create_full_service(self):
        """Create a service with all details."""
        service = DiscoveredService(
            host="192.168.1.1",
            port=80,
            protocol="tcp",
            service="http",
            product="nginx",
            version="1.18.0",
            banner="nginx/1.18.0",
            cpe="cpe:/a:nginx:nginx:1.18.0",
        )

        assert service.product == "nginx"
        assert service.version == "1.18.0"
        assert service.cpe is not None and "nginx" in service.cpe


class TestDiscoveredWebApp:
    """Tests for DiscoveredWebApp model."""

    def test_create_webapp(self):
        """Create a web app discovery."""
        webapp = DiscoveredWebApp(
            url="https://example.com",
            technologies=["WordPress", "PHP", "nginx"],
        )

        assert webapp.url == "https://example.com"
        assert "WordPress" in webapp.technologies

    def test_webapp_with_endpoints(self):
        """Web app with discovered endpoints."""
        webapp = DiscoveredWebApp(
            url="https://api.example.com",
            technologies=["Node.js", "Express"],
            endpoints=["/api/v1/users", "/api/v1/orders", "/health"],
            authentication="jwt",
        )

        assert len(webapp.endpoints) == 3
        assert webapp.authentication == "jwt"


class TestVulnerability:
    """Tests for Vulnerability model."""

    def test_create_vulnerability(self):
        """Create a vulnerability."""
        vuln = Vulnerability(
            id="vuln-001",
            title="SQL Injection in login form",
            severity="high",
            cve_id="CVE-2023-12345",
            cvss=8.5,
            exploitable=True,
        )

        assert vuln.id == "vuln-001"
        assert vuln.severity == "high"
        assert vuln.cvss == 8.5
        assert vuln.exploitable is True

    def test_vulnerability_with_service(self):
        """Vulnerability linked to a service."""
        service = DiscoveredService(
            host="192.168.1.1",
            port=80,
            service="http",
        )

        vuln = Vulnerability(
            id="vuln-002",
            title="XSS in search",
            severity="medium",
            service=service,
        )

        assert vuln.service is not None
        assert vuln.service.port == 80


class TestAttackVector:
    """Tests for AttackVector model."""

    def test_create_attack_vector(self):
        """Create a basic attack vector."""
        vector = AttackVector(
            id="vec-001",
            name="SQL Injection on Login",
            description="Attempt SQL injection on the login form",
            priority=VectorPriority.HIGH,
            target_type="webapp",
            target_ref="https://example.com/login",
        )

        assert vector.id == "vec-001"
        assert vector.priority == VectorPriority.HIGH
        assert vector.status == VectorStatus.PENDING

    def test_vector_with_tools_and_payloads(self):
        """Vector with suggested tools and payloads."""
        vector = AttackVector(
            id="vec-002",
            name="SSH Brute Force",
            description="Brute force SSH credentials",
            priority=VectorPriority.LOW,
            target_type="service",
            target_ref="192.168.1.1:22",
            suggested_tools=["hydra", "medusa"],
            payloads=["rockyou.txt", "common-passwords.txt"],
            max_attempts=5,
        )

        assert "hydra" in vector.suggested_tools
        assert vector.max_attempts == 5

    def test_can_retry_property(self):
        """Test can_retry property."""
        vector = AttackVector(
            id="vec-003",
            name="Test Vector",
            description="Test",
            priority=VectorPriority.MEDIUM,
            target_type="service",
            target_ref="test",
            max_attempts=3,
        )

        # Initially can't retry (not failed yet)
        assert vector.can_retry is False

        # After failing, should be able to retry
        vector.status = VectorStatus.FAILED
        assert vector.can_retry is True

        # After max attempts, can't retry
        vector.attempts = [
            ExploitAttempt(tool_used="test", success=False),
            ExploitAttempt(tool_used="test", success=False),
            ExploitAttempt(tool_used="test", success=False),
        ]
        assert vector.can_retry is False

    def test_attempts_remaining_property(self):
        """Test attempts_remaining property."""
        vector = AttackVector(
            id="vec-004",
            name="Test Vector",
            description="Test",
            priority=VectorPriority.MEDIUM,
            target_type="service",
            target_ref="test",
            max_attempts=3,
        )

        assert vector.attempts_remaining == 3

        vector.attempts.append(ExploitAttempt(tool_used="test", success=False))
        assert vector.attempts_remaining == 2

        vector.attempts.append(ExploitAttempt(tool_used="test", success=False))
        assert vector.attempts_remaining == 1


class TestExploitAttempt:
    """Tests for ExploitAttempt model."""

    def test_create_successful_attempt(self):
        """Create a successful exploit attempt."""
        attempt = ExploitAttempt(
            tool_used="sqlmap",
            payload="' OR 1=1--",
            success=True,
            output="Database dumped successfully",
        )

        assert attempt.success is True
        assert "dumped" in attempt.output

    def test_create_failed_attempt(self):
        """Create a failed exploit attempt."""
        attempt = ExploitAttempt(
            tool_used="hydra",
            success=False,
            error="Connection refused",
            blocked_by="firewall",
            suggestion="Try a different port or use VPN",
        )

        assert attempt.success is False
        assert attempt.blocked_by == "firewall"
        assert attempt.suggestion is not None

    def test_attempt_has_timestamp(self):
        """Attempt should have timestamp."""
        attempt = ExploitAttempt(tool_used="nmap", success=True)

        assert attempt.timestamp is not None
        assert isinstance(attempt.timestamp, datetime)


class TestAttackSurface:
    """Tests for AttackSurface model."""

    @pytest.fixture
    def attack_surface(self):
        """Create an empty attack surface."""
        return AttackSurface()

    def test_empty_attack_surface(self, attack_surface):
        """Empty attack surface should initialize correctly."""
        assert attack_surface.services == []
        assert attack_surface.vulnerabilities == []
        assert attack_surface.vectors == []

    def test_add_service(self, attack_surface):
        """Add a service to attack surface."""
        service = DiscoveredService(
            host="192.168.1.1",
            port=22,
            service="ssh",
        )
        attack_surface.services.append(service)

        assert len(attack_surface.services) == 1
        assert attack_surface.services[0].port == 22

    def test_add_vector(self, attack_surface):
        """Add an attack vector."""
        vector = AttackVector(
            id="vec-001",
            name="Test Attack",
            description="Test",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="test",
        )
        attack_surface.add_vector(vector)

        assert len(attack_surface.vectors) == 1

    def test_get_next_vector_by_priority(self, attack_surface):
        """get_next_vector should return highest priority pending vector."""
        # Add vectors in non-priority order
        low_vec = AttackVector(
            id="vec-low",
            name="Low Priority",
            description="Test",
            priority=VectorPriority.LOW,
            target_type="service",
            target_ref="test",
        )
        critical_vec = AttackVector(
            id="vec-critical",
            name="Critical Priority",
            description="Test",
            priority=VectorPriority.CRITICAL,
            target_type="service",
            target_ref="test",
        )
        medium_vec = AttackVector(
            id="vec-medium",
            name="Medium Priority",
            description="Test",
            priority=VectorPriority.MEDIUM,
            target_type="service",
            target_ref="test",
        )

        attack_surface.add_vector(low_vec)
        attack_surface.add_vector(critical_vec)
        attack_surface.add_vector(medium_vec)

        next_vec = attack_surface.get_next_vector()

        assert next_vec is not None
        assert next_vec.id == "vec-critical"

    def test_get_next_vector_skips_completed(self, attack_surface):
        """get_next_vector should skip completed vectors."""
        completed_vec = AttackVector(
            id="vec-done",
            name="Completed",
            description="Test",
            priority=VectorPriority.CRITICAL,
            status=VectorStatus.SUCCESS,
            target_type="service",
            target_ref="test",
        )
        pending_vec = AttackVector(
            id="vec-pending",
            name="Pending",
            description="Test",
            priority=VectorPriority.HIGH,
            status=VectorStatus.PENDING,
            target_type="service",
            target_ref="test",
        )

        attack_surface.add_vector(completed_vec)
        attack_surface.add_vector(pending_vec)

        next_vec = attack_surface.get_next_vector()

        assert next_vec is not None
        assert next_vec.id == "vec-pending"

    def test_mark_vector_started(self, attack_surface):
        """mark_vector_started should update status."""
        vector = AttackVector(
            id="vec-001",
            name="Test",
            description="Test",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="test",
        )
        attack_surface.add_vector(vector)

        attack_surface.mark_vector_started("vec-001")

        assert attack_surface.vectors[0].status == VectorStatus.IN_PROGRESS

    def test_record_attempt(self, attack_surface):
        """record_attempt should add attempt to vector."""
        vector = AttackVector(
            id="vec-001",
            name="Test",
            description="Test",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="test",
        )
        attack_surface.add_vector(vector)

        attempt = ExploitAttempt(
            tool_used="sqlmap",
            success=True,
            output="Success!",
        )
        attack_surface.record_attempt("vec-001", attempt)

        assert len(attack_surface.vectors[0].attempts) == 1
        assert attack_surface.vectors[0].status == VectorStatus.SUCCESS

    def test_record_failed_attempt(self, attack_surface):
        """record_attempt with failure should update status correctly."""
        vector = AttackVector(
            id="vec-001",
            name="Test",
            description="Test",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="test",
            max_attempts=2,
        )
        attack_surface.add_vector(vector)

        # First failed attempt
        attempt1 = ExploitAttempt(tool_used="test", success=False)
        attack_surface.record_attempt("vec-001", attempt1)
        assert attack_surface.vectors[0].status == VectorStatus.FAILED

        # Second failed attempt - should still be failed
        attempt2 = ExploitAttempt(tool_used="test", success=False)
        attack_surface.record_attempt("vec-001", attempt2)
        assert attack_surface.vectors[0].status == VectorStatus.FAILED
        assert len(attack_surface.vectors[0].attempts) == 2

    def test_get_summary(self, attack_surface):
        """get_summary should return correct counts."""
        # Add services
        attack_surface.services.append(
            DiscoveredService(host="192.168.1.1", port=22, service="ssh")
        )
        attack_surface.services.append(
            DiscoveredService(host="192.168.1.1", port=80, service="http")
        )

        # Add vulnerabilities
        attack_surface.vulnerabilities.append(
            Vulnerability(id="v1", title="Test Vuln", severity="high")
        )

        # Add vectors
        attack_surface.add_vector(AttackVector(
            id="vec-1", name="V1", description="", priority=VectorPriority.HIGH,
            target_type="service", target_ref="test", status=VectorStatus.SUCCESS
        ))
        attack_surface.add_vector(AttackVector(
            id="vec-2", name="V2", description="", priority=VectorPriority.MEDIUM,
            target_type="service", target_ref="test", status=VectorStatus.FAILED
        ))
        attack_surface.add_vector(AttackVector(
            id="vec-3", name="V3", description="", priority=VectorPriority.LOW,
            target_type="service", target_ref="test", status=VectorStatus.PENDING
        ))

        summary = attack_surface.get_summary()

        assert summary["services"] == 2
        assert summary["vulnerabilities"] == 1
        assert summary["vectors_total"] == 3
        assert summary["vectors_success"] == 1
        assert summary["vectors_failed"] == 1
        assert summary["vectors_pending"] == 1


class TestRetryStrategy:
    """Tests for RetryStrategy model."""

    def test_default_retry_strategy(self):
        """Default retry strategy should have empty lists."""
        strategy = RetryStrategy()

        assert strategy.payload_variations == []
        assert strategy.encoding_options == []
        assert strategy.waf_bypass_techniques == []

    def test_custom_retry_strategy(self):
        """Custom retry strategy should work."""
        strategy = RetryStrategy(
            payload_variations=["payload1", "payload2"],
            encoding_options=[None, "base64", "url"],
            waf_bypass_techniques=["case_variation", "comment_injection"],
        )

        assert len(strategy.payload_variations) == 2
        assert len(strategy.encoding_options) == 3
        assert "case_variation" in strategy.waf_bypass_techniques
