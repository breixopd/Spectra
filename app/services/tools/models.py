"""
Pydantic models for the Dynamic Tool Registry.

Defines the schema for tool plugins including installation,
execution, parsing, and UI configuration.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskLevel


class ToolCategory(str, Enum):
    """Primary categories for security tools."""

    DISCOVERY = "discovery"
    ENUMERATION = "enumeration"
    VULNERABILITY = "vulnerability"
    EXPLOITATION = "exploitation"
    POST_EXPLOITATION = "post_exploitation"
    SECRETS = "secrets"
    WEB = "web"
    NETWORK = "network"
    CUSTOM = "custom"


class ToolCapability(str, Enum):
    """
    Fine-grained capabilities that tools can provide.

    Tools can have multiple capabilities, allowing the AI
    to select tools based on specific needs.
    """

    # Discovery capabilities
    PORT_SCAN = "port_scan"
    SERVICE_DETECTION = "service_detection"
    OS_DETECTION = "os_detection"
    HOST_DISCOVERY = "host_discovery"

    # Enumeration capabilities
    SUBDOMAIN_ENUM = "subdomain_enum"
    DIRECTORY_BRUTE = "directory_brute"
    DNS_ENUM = "dns_enum"
    VHOST_DISCOVERY = "vhost_discovery"
    PARAMETER_FUZZING = "parameter_fuzzing"

    # Web capabilities
    WEB_CRAWL = "web_crawl"
    WEB_FINGERPRINT = "web_fingerprint"
    CMS_DETECTION = "cms_detection"
    WAF_DETECTION = "waf_detection"

    # Vulnerability capabilities
    VULN_SCAN = "vuln_scan"
    CVE_DETECTION = "cve_detection"
    MISCONFIG_DETECTION = "misconfig_detection"

    # Exploitation capabilities
    SQL_INJECTION = "sql_injection"
    COMMAND_INJECTION = "command_injection"
    FILE_UPLOAD = "file_upload"
    AUTH_BYPASS = "auth_bypass"
    BRUTE_FORCE = "brute_force"
    CREDENTIAL_SPRAY = "credential_spray"
    EXPLOIT_FRAMEWORK = "exploit_framework"

    # Post-exploitation
    PRIVILEGE_ESCALATION = "privilege_escalation"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFIL = "data_exfil"
    PERSISTENCE = "persistence"

    # Secrets
    SECRET_SCAN = "secret_scan"
    CREDENTIAL_HARVEST = "credential_harvest"


class TargetType(str, Enum):
    """Types of targets a tool can operate on."""

    IP = "ip"
    IP_RANGE = "ip_range"
    CIDR = "cidr"
    DOMAIN = "domain"
    URL = "url"
    HOST = "host"
    FILE = "file"
    ANY = "any"


class ToolStatus(str, Enum):
    """Installation/availability status of a tool."""

    PENDING = "pending"
    INSTALLING = "installing"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


class InstallationMethod(str, Enum):
    """How the tool should be installed."""

    SCRIPT = "script"  # Run shell commands
    APT = "apt"  # apt-get install
    PIPX = "pipx"  # pipx install (isolated Python)
    GO = "go"  # go install
    BINARY = "binary"  # Download pre-built binary
    NONE = "none"  # Already installed (built-in)


class OutputFormat(str, Enum):
    """Output format of the tool."""

    JSON = "json"
    XML = "xml"
    TEXT = "text"
    NDJSON = "ndjson"
    CSV = "csv"


# --- Sub-Models ---


class InstallationConfig(BaseModel):
    """Configuration for tool installation."""

    method: InstallationMethod = Field(
        default=InstallationMethod.SCRIPT, description="Installation method"
    )
    commands: list[str] = Field(
        default_factory=list, description="Shell commands to run for installation"
    )
    verification_command: str | None = Field(
        None,
        description="Command to verify successful installation (e.g., 'nmap --version')",
    )
    verification_regex: str | None = Field(
        None, description="Regex to match against verification output"
    )
    uninstall_commands: list[str] = Field(
        default_factory=list, description="Shell commands to run for uninstallation"
    )


class ExecutionConfig(BaseModel):
    """Configuration for tool execution."""

    command: str = Field(..., description="The base command to run (e.g., 'nmap')")
    args_template: str = Field(
        "",
        description="Argument template with placeholders (e.g., '-sV {target} -oX {output_file}')",
    )
    args_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for arguments validation"
    )
    timeout: int = Field(300, description="Default timeout in seconds")
    timeout_per_host: int = Field(
        60, description="Estimated seconds per host for dynamic timeout calculation"
    )
    min_timeout: int = Field(
        60, description="Minimum timeout regardless of calculation"
    )
    max_timeout: int = Field(3600, description="Maximum timeout cap (1 hour default)")
    working_dir: str | None = Field(None, description="Working directory for execution")
    env: dict[str, str] = Field(
        default_factory=dict, description="Additional environment variables"
    )
    arg_modifiers: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Modifiers for arguments (e.g., {'ports': {'prefix': '-p', 'separator': ','}})",
    )
    success_exit_codes: list[int] = Field(
        default_factory=lambda: [0],
        description="Exit codes considered successful (some tools return non-zero on success)",
    )


class ParsingConfig(BaseModel):
    """Configuration for parsing tool output.

    Supports multiple parsing strategies:
    1. format=json/xml/csv: Structured parsing with field mapping
    2. format=text + regex_patterns: Extract data via regex
    3. format=text + llm_extraction=True: Use LLM to extract findings (universal)
    """

    format: OutputFormat = Field(
        OutputFormat.TEXT, description="Output format of the tool"
    )
    mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Field mapping from tool output to Spectra's Finding model",
    )

    # Universal parsing via regex patterns
    regex_patterns: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of regex patterns with named groups to extract findings. "
        "Each dict has 'pattern' and optional 'type' (service|vuln|info)",
    )

    # LLM-based extraction for complex/unknown formats
    llm_extraction: bool = Field(
        False, description="Use LLM to extract structured findings from text output"
    )
    extraction_hint: str = Field(
        "",
        description="Hint to LLM about what kind of data to extract (e.g., 'ports and services')",
    )

    jq_filter: str | None = Field(
        None, description="Optional jq filter for JSON output"
    )
    output_file_pattern: str | None = Field(
        None, description="Glob pattern for output files if tool writes multiple files"
    )
    capture_stderr: bool = Field(
        True, description="Whether to capture stderr in addition to stdout"
    )
    combine_outputs: bool = Field(
        False, description="Combine stdout and output file contents for parsing"
    )


class UIConfig(BaseModel):
    """Configuration for UI display."""

    icon: str = Field("terminal", description="Phosphor Icon name")
    color: str = Field("violet", description="Tailwind color name for accents")


class StealthConfig(BaseModel):
    """Stealth mode configuration for a tool."""

    rate_limit: int | None = Field(
        default=None, description="Maximum requests/packets per second in stealth mode"
    )
    delay_ms: int | None = Field(
        default=None, description="Delay between requests in milliseconds"
    )
    extra_args: dict[str, Any] = Field(
        default_factory=dict, description="Additional arguments for stealth mode"
    )


class ToolMetadata(BaseModel):
    """
    Rich metadata for AI-driven tool selection.

    This information helps the AI make informed decisions
    about which tool to use in each scenario.
    """

    # AI-friendly detailed description
    ai_description: str = Field(
        default="",
        description="Detailed description for AI reasoning about when to use this tool",
    )

    # Capabilities this tool provides
    capabilities: list[ToolCapability] = Field(
        default_factory=list, description="List of capabilities this tool provides"
    )

    # What target types this tool accepts
    supported_targets: list[TargetType] = Field(
        default_factory=lambda: [TargetType.ANY],
        description="Types of targets this tool can operate on",
    )

    # Risk level of using this tool
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW, description="Risk level of running this tool"
    )

    # Tags for flexible categorization
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tags (e.g., 'wordpress', 'api', 'active-directory')",
    )

    # Use cases - when to use this tool
    use_cases: list[str] = Field(
        default_factory=list, description="Specific scenarios where this tool excels"
    )

    # When NOT to use this tool
    limitations: list[str] = Field(
        default_factory=list,
        description="Known limitations or scenarios where this tool is not suitable",
    )

    # Tools that work well together with this one
    complements: list[str] = Field(
        default_factory=list, description="Tool IDs that complement this tool"
    )

    # Tools that should run before this one
    prerequisites: list[str] = Field(
        default_factory=list,
        description="Tool IDs that should typically run before this tool",
    )


# --- Main Plugin Model ---


class ToolConfig(BaseModel):
    """
    Complete configuration for a security tool plugin.

    This is the schema for tool_config.json files.
    """

    id: str = Field(
        ...,
        description="Unique identifier (lowercase, hyphens allowed)",
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    name: str = Field(..., description="Human-readable display name")
    version: str = Field(
        ..., description="Semantic version (e.g., '1.0.0')", pattern=r"^\d+\.\d+\.\d+$"
    )
    category: ToolCategory = Field(
        ..., description="Primary tool category for organization"
    )
    description: str = Field(..., description="Brief description of what the tool does")

    # NEW: Rich metadata for AI
    metadata: ToolMetadata = Field(
        default_factory=lambda: ToolMetadata(),
        description="Rich metadata for AI-driven tool selection",
    )

    installation: InstallationConfig = Field(
        default_factory=lambda: InstallationConfig(method=InstallationMethod.SCRIPT),  # type: ignore[call-arg]
        description="Installation configuration",
    )
    execution: ExecutionConfig = Field(..., description="Execution configuration")
    parsing: ParsingConfig = Field(
        default_factory=lambda: ParsingConfig(format=OutputFormat.TEXT),  # type: ignore[call-arg]
        description="Output parsing configuration",
    )
    ui: UIConfig = Field(
        default_factory=lambda: UIConfig(icon="terminal", color="violet"),
        description="UI display configuration",
    )

    # NEW: Stealth configuration
    stealth: StealthConfig = Field(
        default_factory=lambda: StealthConfig(),
        description="Stealth mode configuration",
    )

    # Security
    signature: str | None = Field(
        None, description="Ed25519 signature of the plugin (hex-encoded)"
    )
    is_system: bool = Field(
        default=False,
        description="Whether this is a built-in system tool that cannot be removed",
    )

    model_config = ConfigDict(use_enum_values=True)

    def get_ai_summary(self) -> str:
        """Generate a comprehensive summary for AI tool selection."""
        parts = [
            f"**{self.name}** ({self.id})",
            f"Category: {self.category}",
            f"Description: {self.description}",
        ]

        if self.metadata.ai_description:
            parts.append(f"Details: {self.metadata.ai_description}")

        if self.metadata.capabilities:
            parts.append(f"Capabilities: {', '.join(self.metadata.capabilities)}")

        if self.metadata.use_cases:
            parts.append(f"Best for: {'; '.join(self.metadata.use_cases)}")

        if self.metadata.limitations:
            parts.append(f"Limitations: {'; '.join(self.metadata.limitations)}")

        if self.metadata.tags:
            parts.append(f"Tags: {', '.join(self.metadata.tags)}")

        parts.append(f"Risk: {self.metadata.risk_level}")

        return "\n".join(parts)


# --- Registry Models ---


class RegisteredTool(BaseModel):
    """A tool registered in the system with its current status."""

    config: ToolConfig
    status: ToolStatus = ToolStatus.PENDING
    installed_version: str | None = None
    error_message: str | None = None

    @property
    def is_available(self) -> bool:
        """Check if the tool is ready to use."""
        return self.status == ToolStatus.READY


class ToolExecutionRequest(BaseModel):
    """Request to execute a tool."""

    tool_id: str = Field(..., description="ID of the tool to run")
    target: str = Field(..., description="Target for the tool (IP, URL, domain)")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Additional arguments to pass to the tool"
    )
    timeout: int | None = Field(None, description="Override the default timeout")


class ToolExecutionResult(BaseModel):
    """Result from a tool execution."""

    tool_id: str
    target: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    output_file: str | None = None
    parsed_findings: list[dict[str, Any]] = Field(default_factory=list)
