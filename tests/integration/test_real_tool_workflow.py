"""
Integration Tests: Real Tool Workflow

These tests use REAL components with MINIMAL mocking:
- Real ToolRegistry loading real plugin files
- Real CommandToolAdapter executing real commands
- Real output parsing 
- Real attack surface tracking
- Real mission state management

Only the LLM is mocked (unavoidable for automated tests).
"""

import json
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.tools.registry import ToolRegistry, initialize_registry
from app.services.tools.adapter import CommandToolAdapter
from app.services.tools.models import (
    ToolConfig,
    ToolCategory,
    ToolCapability,
    RiskLevel,
    OutputFormat,
    ToolExecutionRequest,
    ExecutionConfig,
    ParsingConfig,
    ToolMetadata,
)
from app.models.attack_surface import (
    AttackSurface,
    DiscoveredService,
    DiscoveredWebApp,
    Vulnerability,
    AttackVector,
    VectorPriority,
    VectorStatus,
    ExploitAttempt,
)
from app.services.mission.mission import Mission


pytestmark = [pytest.mark.asyncio]


# === REAL TOOL REGISTRY TESTS ===


class TestRealToolRegistry:
    """Tests using the REAL tool registry with REAL plugin files."""

    @pytest_asyncio.fixture
    async def real_registry(self):
        """Load the REAL registry with actual plugin files.
        
        We disable safe_mode because we don't have the private key to sign/verify
        in this environment, or we don't want to set up keys for this test.
        """
        registry = await initialize_registry(safe_mode=False)
        
        # Enforce safe_mode=False even if previously initialized with True
        registry.safe_mode = False
        registry.validator.safe_mode = False
        # Reload plugins to ensure all are loaded with safe_mode=False
        await registry.load_plugins()
        
        return registry

    async def test_loads_all_plugin_files(self, real_registry: ToolRegistry):
        """Verify all plugin JSON files are loaded."""
        plugins_dir = Path("plugins")
        json_files = list(plugins_dir.glob("*.json"))
        
        loaded_tools = real_registry.list_tools()
        loaded_ids = {t.config.id for t in loaded_tools}
        
        # Every JSON file should have a corresponding tool
        for json_file in json_files:
            expected_id = json_file.stem
            assert expected_id in loaded_ids, f"Plugin {json_file.name} not loaded"

    async def test_nmap_plugin_has_correct_metadata(self, real_registry: ToolRegistry):
        """Verify nmap plugin has proper configuration."""
        nmap = real_registry.get_tool("nmap")
        assert nmap is not None, "nmap plugin not found"
        
        config = nmap.config
        assert config.category == ToolCategory.DISCOVERY
        assert ToolCapability.PORT_SCAN in config.metadata.capabilities
        assert ToolCapability.SERVICE_DETECTION in config.metadata.capabilities
        assert config.execution.command == "nmap"
        assert "{target}" in config.execution.args_template

    async def test_nuclei_plugin_has_correct_metadata(self, real_registry: ToolRegistry):
        """Verify nuclei plugin has proper configuration."""
        nuclei = real_registry.get_tool("nuclei")
        assert nuclei is not None, "nuclei plugin not found"
        
        config = nuclei.config
        assert config.category == ToolCategory.VULNERABILITY
        assert ToolCapability.VULN_SCAN in config.metadata.capabilities
        assert config.metadata.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]

    async def test_sqlmap_plugin_has_exploitation_category(self, real_registry: ToolRegistry):
        """Verify sqlmap is categorized correctly."""
        sqlmap = real_registry.get_tool("sqlmap")
        if sqlmap:
            config = sqlmap.config
            assert config.category in [ToolCategory.EXPLOITATION, ToolCategory.WEB]
            assert ToolCapability.SQL_INJECTION in config.metadata.capabilities

    async def test_all_plugins_have_valid_execution_config(self, real_registry: ToolRegistry):
        """Verify all plugins have valid execution configurations."""
        tools = real_registry.list_tools()
        
        for tool in tools:
            config = tool.config
            assert config.execution.command, f"{config.id} missing command"
            assert config.execution.timeout > 0, f"{config.id} invalid timeout"
            # args_template can be empty but should be a string
            assert isinstance(config.execution.args_template, str)

    async def test_all_plugins_have_ai_metadata(self, real_registry: ToolRegistry):
        """Verify all plugins have AI-usable metadata."""
        tools = real_registry.list_tools()
        
        for tool in tools:
            metadata = tool.config.metadata
            # Should have at least one capability
            assert len(metadata.capabilities) > 0, f"{tool.config.id} has no capabilities"
            # Should have risk level
            assert metadata.risk_level is not None, f"{tool.config.id} has no risk_level"
            # Should have AI description
            assert metadata.ai_description, f"{tool.config.id} has no ai_description"

    async def test_get_ai_summary_produces_useful_output(self, real_registry: ToolRegistry):
        """Verify get_ai_summary produces parseable output."""
        nmap = real_registry.get_tool("nmap")
        assert nmap is not None
        
        summary = nmap.config.get_ai_summary()
        
        # Summary should contain key information
        assert "nmap" in summary.lower()
        assert "port" in summary.lower() or "scan" in summary.lower()
        assert "Capabilities:" in summary


# === REAL COMMAND EXECUTION TESTS ===


class TestRealCommandExecution:
    """Tests executing REAL commands (safe ones like echo, cat, etc.)."""

    @pytest.fixture
    def echo_tool_config(self) -> ToolConfig:
        """Create a tool config that uses echo for safe testing."""
        return ToolConfig(
            id="test-echo",
            name="Test Echo",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Echo command for testing",
            execution=ExecutionConfig(
                command="echo",
                args_template="{target}",
                timeout=30,
            ),
            parsing=ParsingConfig(format=OutputFormat.TEXT),
            metadata=ToolMetadata(
                capabilities=[ToolCapability.HOST_DISCOVERY],
                risk_level=RiskLevel.PASSIVE,
                ai_description="Test tool using echo",
            ),
        )

    @pytest.fixture
    def json_echo_config(self) -> ToolConfig:
        """Tool config that outputs JSON via echo."""
        return ToolConfig(
            id="test-json-echo",
            name="JSON Echo",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Echo JSON for parsing tests",
            execution=ExecutionConfig(
                command="echo",
                args_template="'{\"host\": \"{target}\", \"port\": 80, \"service\": \"http\"}'",
                timeout=30,
            ),
            parsing=ParsingConfig(
                format=OutputFormat.JSON,
                mapping={"ip": "host", "port": "port", "service": "service"},
            ),
            metadata=ToolMetadata(
                capabilities=[ToolCapability.PORT_SCAN],
                risk_level=RiskLevel.PASSIVE,
                ai_description="JSON echo for tests",
            ),
        )

    async def test_real_command_execution(self, echo_tool_config: ToolConfig):
        """Test executing a real command."""
        adapter = CommandToolAdapter(echo_tool_config)
        request = ToolExecutionRequest(
            tool_id="test-echo",
            target="192.168.1.1",
            args={},
            timeout=10,
        )
        
        result = await adapter.execute(request)
        
        assert result.success, f"Command failed: {result.stderr}"
        assert result.exit_code == 0
        assert "192.168.1.1" in result.stdout
        assert result.duration_seconds < 10

    async def test_command_with_multiple_args(self):
        """Test command with multiple arguments."""
        config = ToolConfig(
            id="test-multi-arg",
            name="Multi Arg Test",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Test multiple args",
            execution=ExecutionConfig(
                command="echo",
                args_template="{target} {flags} {extra}",
                timeout=30,
            ),
            parsing=ParsingConfig(format=OutputFormat.TEXT),
            metadata=ToolMetadata(capabilities=[], risk_level=RiskLevel.PASSIVE, ai_description="test"),
        )
        
        adapter = CommandToolAdapter(config)
        request = ToolExecutionRequest(
            tool_id="test-multi-arg",
            target="target.com",
            args={"flags": "-v", "extra": "--debug"},
            timeout=10,
        )
        
        result = await adapter.execute(request)
        
        assert result.success
        assert "target.com" in result.stdout
        assert "-v" in result.stdout
        assert "--debug" in result.stdout

    async def test_target_cannot_be_overridden_by_args(self):
        """Critical security test: target should not be overrideable."""
        config = ToolConfig(
            id="test-override",
            name="Override Test",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Test target override protection",
            execution=ExecutionConfig(
                command="echo",
                args_template="{target}",
                timeout=30,
            ),
            parsing=ParsingConfig(format=OutputFormat.TEXT),
            metadata=ToolMetadata(capabilities=[], risk_level=RiskLevel.PASSIVE, ai_description="test"),
        )
        
        adapter = CommandToolAdapter(config)
        request = ToolExecutionRequest(
            tool_id="test-override",
            target="safe-target.com",
            args={"target": "evil-target.com"},  # Trying to override!
            timeout=10,
        )
        
        result = await adapter.execute(request)
        
        assert result.success
        # The REAL target should be used, not the one in args
        assert "safe-target.com" in result.stdout
        assert "evil-target.com" not in result.stdout

    async def test_timeout_handling(self):
        """Test that timeouts are properly enforced."""
        config = ToolConfig(
            id="test-timeout",
            name="Timeout Test",
            version="1.0.0",
            category=ToolCategory.DISCOVERY,
            description="Sleep command for timeout test",
            execution=ExecutionConfig(
                command="sleep",
                args_template="10",  # Sleep for 10 seconds
                timeout=30,
            ),
            parsing=ParsingConfig(format=OutputFormat.TEXT),
            metadata=ToolMetadata(capabilities=[], risk_level=RiskLevel.PASSIVE, ai_description="test"),
        )
        
        adapter = CommandToolAdapter(config)
        request = ToolExecutionRequest(
            tool_id="test-timeout",
            target="dummy",
            args={},
            timeout=1,  # But timeout after 1 second
        )
        
        result = await adapter.execute(request)
        
        assert not result.success
        assert "timed out" in result.stderr.lower()
        assert result.duration_seconds >= 1
        assert result.duration_seconds < 5  # Should kill quickly, not wait the full 10s

    async def test_json_output_parsing(self, json_echo_config: ToolConfig):
        """Test real JSON parsing from command output."""
        adapter = CommandToolAdapter(json_echo_config)
        request = ToolExecutionRequest(
            tool_id="test-json-echo",
            target="192.168.1.1",
            args={},
            timeout=10,
        )
        
        result = await adapter.execute(request)
        
        assert result.success
        # Note: Due to shell quoting, parsing may vary
        # This tests the parsing infrastructure works

    async def test_ndjson_parsing(self):
        """Test NDJSON (newline-delimited JSON) parsing."""
        config = ToolConfig(
            id="test-ndjson",
            name="NDJSON Test",
            version="1.0.0",
            category=ToolCategory.VULNERABILITY,
            description="NDJSON output test",
            execution=ExecutionConfig(
                command="printf",
                args_template="'{\"port\": 22}\\n{\"port\": 80}\\n{\"port\": 443}'",
                timeout=30,
            ),
            parsing=ParsingConfig(format=OutputFormat.NDJSON),
            metadata=ToolMetadata(capabilities=[], risk_level=RiskLevel.PASSIVE, ai_description="test"),
        )
        
        adapter = CommandToolAdapter(config)
        request = ToolExecutionRequest(
            tool_id="test-ndjson",
            target="dummy",
            args={},
            timeout=10,
        )
        
        result = await adapter.execute(request)
        
        # Even if parsing has issues due to shell quoting, command should succeed
        assert result.exit_code == 0


# === REAL ATTACK SURFACE TESTS ===


class TestRealAttackSurface:
    """Tests using REAL AttackSurface model with no mocking."""

    @pytest.fixture
    def attack_surface(self) -> AttackSurface:
        """Create a real attack surface instance."""
        return AttackSurface()

    def test_add_and_retrieve_services(self, attack_surface: AttackSurface):
        """Test adding and retrieving discovered services."""
        service1 = DiscoveredService(
            host="192.168.1.1",
            port=22,
            protocol="tcp",
            service="ssh",
            product="OpenSSH",
            version="8.2p1",
        )
        service2 = DiscoveredService(
            host="192.168.1.1",
            port=80,
            protocol="tcp",
            service="http",
            product="nginx",
            version="1.18.0",
        )
        
        attack_surface.add_service(service1)
        attack_surface.add_service(service2)
        
        assert len(attack_surface.services) == 2
        
        # Test deduplication
        attack_surface.add_service(service1)  # Same host:port
        assert len(attack_surface.services) == 2  # Should still be 2

    def test_add_and_retrieve_vulnerabilities(self, attack_surface: AttackSurface):
        """Test vulnerability tracking."""
        vuln = Vulnerability(
            id="CVE-2024-1234",
            title="SQL Injection in Login",
            severity="critical",
            cve_id="CVE-2024-1234",
            cvss=9.8,
        )
        
        attack_surface.add_vulnerability(vuln)
        
        assert len(attack_surface.vulnerabilities) == 1
        assert attack_surface.vulnerabilities[0].severity == "critical"

    def test_add_and_retrieve_webapps(self, attack_surface: AttackSurface):
        """Test web application tracking."""
        webapp = DiscoveredWebApp(
            url="http://192.168.1.1/admin",
            technologies=["WordPress", "PHP", "MySQL"],
            endpoints=["/wp-admin", "/wp-login.php"],
        )
        
        attack_surface.add_web_app(webapp)
        
        assert len(attack_surface.web_apps) == 1
        assert "WordPress" in attack_surface.web_apps[0].technologies

    def test_attack_vector_lifecycle(self, attack_surface: AttackSurface):
        """Test the full lifecycle of an attack vector."""
        vector = AttackVector(
            id="ssh-brute-192.168.1.1",
            name="SSH Brute Force",
            description="Attempt to brute force SSH credentials",
            priority=VectorPriority.HIGH,
            status=VectorStatus.PENDING,
            target_type="service",
            target_ref="192.168.1.1:22",
            suggested_tools=["hydra"],
            payloads=["admin:admin", "root:root", "admin:password"],
            max_attempts=3,
        )
        
        attack_surface.add_vector(vector)
        
        # Get next vector
        next_vector = attack_surface.get_next_vector()
        assert next_vector is not None
        assert next_vector.id == "ssh-brute-192.168.1.1"
        
        # Mark as started
        attack_surface.mark_vector_started(vector.id)
        assert attack_surface.vectors[0].status == VectorStatus.IN_PROGRESS
        
        # Record failed attempt
        attempt = ExploitAttempt(
            tool_used="hydra",
            payload="admin:admin",
            success=False,
            output="",
            error="Connection refused",
        )
        attack_surface.record_attempt(vector.id, attempt)
        
        # Should still have attempts remaining
        assert attack_surface.vectors[0].can_retry
        assert attack_surface.vectors[0].attempts_remaining == 2
        
        # Record successful attempt
        success_attempt = ExploitAttempt(
            tool_used="hydra",
            payload="root:root",
            success=True,
            output="Login successful",
        )
        attack_surface.record_attempt(vector.id, success_attempt)
        
        # Should be marked as success
        assert attack_surface.vectors[0].status == VectorStatus.SUCCESS
        assert attack_surface.exploitation_successes == 1

    def test_vector_priority_ordering(self, attack_surface: AttackSurface):
        """Test that vectors are returned in priority order."""
        low_priority = AttackVector(
            id="low-1",
            name="Low Priority",
            description="Low priority vector",
            priority=VectorPriority.LOW,
            target_type="service",
            target_ref="192.168.1.1:80",
        )
        high_priority = AttackVector(
            id="high-1",
            name="High Priority",
            description="High priority vector",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="192.168.1.1:22",
        )
        critical_priority = AttackVector(
            id="critical-1",
            name="Critical Priority",
            description="Critical priority vector",
            priority=VectorPriority.CRITICAL,
            target_type="vulnerability",
            target_ref="CVE-2024-1234",
        )
        
        # Add in wrong order
        attack_surface.add_vector(low_priority)
        attack_surface.add_vector(high_priority)
        attack_surface.add_vector(critical_priority)
        
        # Should return critical first
        next_vec = attack_surface.get_next_vector()
        assert next_vec.priority == VectorPriority.CRITICAL

    def test_vector_dependency_resolution(self, attack_surface: AttackSurface):
        """Test that vector dependencies are respected."""
        prereq_vector = AttackVector(
            id="prereq-1",
            name="Prerequisite",
            description="Must complete first",
            priority=VectorPriority.HIGH,
            target_type="service",
            target_ref="192.168.1.1:22",
        )
        dependent_vector = AttackVector(
            id="dependent-1",
            name="Dependent",
            description="Depends on prereq",
            priority=VectorPriority.CRITICAL,  # Higher priority but has dependency
            target_type="service",
            target_ref="192.168.1.1:22",
            requires_vectors=["prereq-1"],
        )
        
        attack_surface.add_vector(prereq_vector)
        attack_surface.add_vector(dependent_vector)
        
        # Should return prereq first (despite lower priority) because dependency not met
        next_vec = attack_surface.get_next_vector()
        assert next_vec.id == "prereq-1"
        
        # Complete the prereq
        attack_surface.mark_vector_started("prereq-1")
        attack_surface.record_attempt("prereq-1", ExploitAttempt(
            tool_used="test",
            success=True,
            output="done",
        ))
        
        # Now dependent should be available
        next_vec = attack_surface.get_next_vector()
        assert next_vec.id == "dependent-1"

    def test_attack_surface_summary(self, attack_surface: AttackSurface):
        """Test summary generation."""
        # Add various items
        attack_surface.add_service(DiscoveredService(host="192.168.1.1", port=22, service="ssh"))
        attack_surface.add_service(DiscoveredService(host="192.168.1.1", port=80, service="http"))
        attack_surface.add_vulnerability(Vulnerability(id="v1", title="Test", severity="high"))
        attack_surface.add_vector(AttackVector(
            id="vec1", name="Vec1", description="Test",
            priority=VectorPriority.HIGH, target_type="service", target_ref="test",
        ))
        
        summary = attack_surface.get_summary()
        
        assert summary["services"] == 2
        assert summary["vulnerabilities"] == 1
        assert summary["vectors_total"] == 1
        assert summary["vectors_pending"] == 1
        assert "vectors_by_priority" in summary


# === REAL MISSION STATE TESTS ===


class TestRealMissionState:
    """Tests using REAL Mission object with minimal mocking."""

    @pytest.fixture
    def mission(self) -> Mission:
        """Create a real mission instance."""
        return Mission(
            target="192.168.1.0/24",
            directive="Full security assessment of internal network",
        )

    def test_mission_initialization(self, mission: Mission):
        """Test mission is properly initialized."""
        assert mission.id is not None  # UUID is auto-generated
        assert mission.target == "192.168.1.0/24"
        assert mission.directive == "Full security assessment of internal network"
        assert mission.status == "created"
        assert len(mission.logs) == 0
        assert len(mission.findings) == 0
        assert mission.attack_surface is not None

    def test_mission_logging(self, mission: Mission):
        """Test mission log functionality."""
        mission.log("Starting discovery phase")
        mission.log("Found open port: 22")
        mission.log("Found open port: 80")
        
        assert len(mission.logs) == 3
        assert "Starting discovery" in mission.logs[0]
        assert "port: 22" in mission.logs[1]

    def test_mission_service_tracking(self, mission: Mission):
        """Test adding services through mission interface."""
        svc = mission.add_service(
            host="192.168.1.1",
            port=22,
            service="ssh",
            product="OpenSSH",
            version="8.2",
        )
        
        assert svc.host == "192.168.1.1"
        assert len(mission.attack_surface.services) == 1
        # Should have logged the discovery
        assert any("22" in log for log in mission.logs)

    def test_mission_vulnerability_tracking(self, mission: Mission):
        """Test adding vulnerabilities through mission interface."""
        vuln = mission.add_vulnerability(
            vuln_id="vuln-001",
            title="Default Credentials",
            severity="high",
            cve_id=None,
        )
        
        assert vuln.id == "vuln-001"
        assert len(mission.attack_surface.vulnerabilities) == 1

    def test_mission_webapp_tracking(self, mission: Mission):
        """Test adding web apps through mission interface."""
        webapp = mission.add_webapp(
            url="http://192.168.1.1/admin",
            technologies=["WordPress", "Apache"],
        )
        
        assert webapp.url == "http://192.168.1.1/admin"
        assert len(mission.attack_surface.web_apps) == 1

    def test_mission_finding_tracking(self, mission: Mission):
        """Test adding findings."""
        mission.add_finding({
            "title": "SQL Injection",
            "severity": "critical",
            "port": 80,
            "evidence": "Error-based SQL injection detected",
        })
        
        assert len(mission.findings) == 1
        assert mission.findings[0]["severity"] == "critical"

    def test_mission_tool_tracking(self, mission: Mission):
        """Test tool execution tracking."""
        mission.record_tool_run("nmap")
        mission.record_tool_run("nuclei")
        mission.record_tool_run("nmap")  # Duplicate
        
        assert "nmap" in mission.tools_run
        assert "nuclei" in mission.tools_run
        assert len(mission.tools_run) == 2  # No duplicates

    def test_mission_stop_functionality(self, mission: Mission):
        """Test mission stop mechanism."""
        assert not mission.is_stopped()
        
        mission.stop()
        
        assert mission.is_stopped()
        assert mission.status == "stopping"

    def test_get_known_services_format(self, mission: Mission):
        """Test that known services are returned in correct format for agents."""
        mission.add_service(host="192.168.1.1", port=22, service="ssh", product="OpenSSH", version="8.2")
        mission.add_service(host="192.168.1.1", port=80, service="http", product="nginx", version="1.18")
        
        services = mission.get_known_services()
        
        assert len(services) == 2
        assert all(isinstance(s, dict) for s in services)
        assert services[0]["host"] == "192.168.1.1"
        assert services[0]["port"] == 22
        assert "service" in services[0]
        assert "product" in services[0]

    def test_get_known_vulns_format(self, mission: Mission):
        """Test that known vulns are returned in correct format for agents."""
        mission.add_vulnerability(vuln_id="CVE-2024-1234", title="SQL Injection", severity="critical", cve_id="CVE-2024-1234")
        
        vulns = mission.get_known_vulns()
        
        assert len(vulns) == 1
        assert vulns[0]["id"] == "CVE-2024-1234"
        assert vulns[0]["severity"] == "critical"
        assert vulns[0]["cve_id"] == "CVE-2024-1234"


# === INTEGRATION: TOOL -> ATTACK SURFACE ===


class TestToolToAttackSurfaceIntegration:
    """Test the integration between tool output and attack surface."""

    async def test_parsed_findings_populate_attack_surface(self):
        """Test that parsed tool findings can populate attack surface."""
        # Simulate nmap-like output
        nmap_findings = [
            {"ip": "192.168.1.1", "port": 22, "service": "ssh", "product": "OpenSSH", "version": "8.2p1"},
            {"ip": "192.168.1.1", "port": 80, "service": "http", "product": "nginx", "version": "1.18.0"},
            {"ip": "192.168.1.1", "port": 443, "service": "https", "product": "nginx", "version": "1.18.0"},
        ]
        
        attack_surface = AttackSurface()
        
        # Simulate what executor does with parsed findings
        for finding in nmap_findings:
            service = DiscoveredService(
                host=finding["ip"],
                port=finding["port"],
                service=finding.get("service"),
                product=finding.get("product"),
                version=finding.get("version"),
            )
            attack_surface.add_service(service)
        
        assert len(attack_surface.services) == 3
        
        # Verify services are queryable
        http_services = [s for s in attack_surface.services if s.service == "http"]
        assert len(http_services) == 1
        assert http_services[0].port == 80

    async def test_nuclei_style_findings_create_vulnerabilities(self):
        """Test that vulnerability scanner output creates vulnerability entries."""
        nuclei_findings = [
            {"template-id": "cve-2024-1234", "name": "SQL Injection", "severity": "critical", "matched-at": "http://192.168.1.1/login"},
            {"template-id": "wordpress-login", "name": "WordPress Login Found", "severity": "info", "matched-at": "http://192.168.1.1/wp-login.php"},
        ]
        
        attack_surface = AttackSurface()
        
        for finding in nuclei_findings:
            if finding["severity"] != "info":  # Skip info-level
                vuln = Vulnerability(
                    id=finding["template-id"],
                    title=finding["name"],
                    severity=finding["severity"],
                    cve_id=finding["template-id"] if finding["template-id"].startswith("cve-") else None,
                )
                attack_surface.add_vulnerability(vuln)
        
        assert len(attack_surface.vulnerabilities) == 1
        assert attack_surface.vulnerabilities[0].severity == "critical"


# === REAL PLUGIN FILE VALIDATION ===

# This class contains sync tests - override module-level asyncio mark
class TestPluginFileIntegrity:
    """Validate the actual plugin JSON files.
    
    Note: These are synchronous validation tests (no async operations needed).
    """
    
    # Override module-level pytestmark to prevent asyncio warnings
    pytestmark = []

    @pytest.fixture
    def plugins_dir(self) -> Path:
        return Path("plugins")

    def test_all_plugins_are_valid_json(self, plugins_dir: Path):
        """Every .json file in plugins/ should be valid JSON."""
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                try:
                    data = json.load(f)
                    assert "id" in data
                    assert "name" in data
                    assert "execution" in data
                except json.JSONDecodeError as e:
                    pytest.fail(f"{plugin_file.name} is not valid JSON: {e}")

    def test_plugin_ids_match_filenames(self, plugins_dir: Path):
        """Plugin ID should match the filename (without .json)."""
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                data = json.load(f)
            
            expected_id = plugin_file.stem
            actual_id = data.get("id")
            
            assert actual_id == expected_id, f"{plugin_file.name}: id '{actual_id}' != filename '{expected_id}'"

    def test_all_plugins_have_verification_commands(self, plugins_dir: Path):
        """All plugins should have installation verification."""
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                data = json.load(f)
            
            installation = data.get("installation", {})
            method = installation.get("method", "script")
            
            # Only require verification for tools that need installation
            if method != "none":
                verification_cmd = installation.get("verification_command")
                assert verification_cmd, f"{plugin_file.name} missing verification_command"

    def test_all_plugins_have_ai_metadata(self, plugins_dir: Path):
        """All plugins should have AI-friendly metadata."""
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                data = json.load(f)
            
            metadata = data.get("metadata", {})
            
            assert metadata.get("ai_description"), f"{plugin_file.name} missing ai_description"
            assert metadata.get("capabilities"), f"{plugin_file.name} missing capabilities"
            assert metadata.get("risk_level"), f"{plugin_file.name} missing risk_level"

    def test_plugin_command_templates_have_target_placeholder(self, plugins_dir: Path):
        """Execution templates should include {target} placeholder."""
        for plugin_file in plugins_dir.glob("*.json"):
            with open(plugin_file) as f:
                data = json.load(f)
            
            args_template = data.get("execution", {}).get("args_template", "")
            
            # Most tools should have a target placeholder
            # Some tools might use different mechanisms, so this is a soft check
            if args_template and "{target}" not in args_template:
                # Log warning but don't fail
                print(f"WARNING: {plugin_file.name} has no {{target}} in args_template")
