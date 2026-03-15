"""
Playbook System - Structured Learning for Pentesting.

Alternative to RAG for pentest knowledge. Instead of vector similarity
search over unstructured text, this uses structured playbooks that map
directly to pentest workflows.

Why playbooks over RAG for pentesting:
1. Pentest patterns are highly structured (service → vuln → exploit)
2. RAG requires embeddings model = heavy dependencies
3. Playbook matches are deterministic, not probabilistic
4. Easier to debug and audit than vector similarity
5. Can be version-controlled as JSON/YAML files

The RAG system is still useful for:
- Free-text CVE description search
- Historical mission context across many targets
- Tool documentation indexing

But for the core "what tool to use for X service" logic, playbooks are
more reliable and don't hallucinate.
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.paths import data_path

logger = logging.getLogger(__name__)


class PlaybookStep(BaseModel):
    """A single step in a pentest playbook."""

    tool: str = Field(..., description="Tool ID to use")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    description: str = Field(..., description="What this step does")
    condition: str | None = Field(
        None, description="When to run (e.g., 'port_80_open')"
    )
    on_success: str | None = Field(None, description="Next step ID on success")
    on_failure: str | None = Field(None, description="Next step ID on failure")


class ServicePlaybook(BaseModel):
    """Playbook for a specific service/port combination."""

    service: str = Field(..., description="Service name (e.g., 'http', 'ssh', 'smb')")
    ports: list[int] = Field(default_factory=list, description="Typical ports")
    steps: list[PlaybookStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ExploitPattern(BaseModel):
    """A known exploit pattern from past successes."""

    service: str
    product: str | None = None
    version_regex: str | None = None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    success_rate: float = 0.0
    last_used: str | None = None
    notes: str = ""


# --- Built-in Playbooks ---

DEFAULT_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "service": "http",
        "ports": [80, 443, 8080, 8443, 8000, 3000],
        "tags": ["web", "common"],
        "steps": [
            {
                "tool": "nmap",
                "args": {"ports": "80,443,8080,8443"},
                "description": "Service version detection on web ports",
            },
            {
                "tool": "nuclei",
                "args": {},
                "description": "Vulnerability scan with nuclei templates",
            },
            {
                "tool": "nikto",
                "args": {},
                "description": "Web server misconfiguration scan",
            },
            {
                "tool": "gobuster",
                "args": {},
                "description": "Directory and file enumeration",
                "condition": "http_found",
            },
            {
                "tool": "ffuf",
                "args": {},
                "description": "Parameter fuzzing on discovered endpoints",
                "condition": "directories_found",
            },
            {
                "tool": "sqlmap",
                "args": {},
                "description": "SQL injection testing on found parameters",
                "condition": "parameters_found",
            },
        ],
    },
    {
        "service": "ssh",
        "ports": [22, 2222],
        "tags": ["remote_access"],
        "steps": [
            {
                "tool": "nmap",
                "args": {
                    "ports": "22",
                    "flags": "--script ssh-auth-methods,ssh-hostkey",
                },
                "description": "SSH version and auth method detection",
            },
            {
                "tool": "hydra",
                "args": {},
                "description": "SSH credential brute force",
                "condition": "password_auth_enabled",
            },
            {
                "tool": "searchsploit",
                "args": {},
                "description": "Search for SSH version exploits",
                "condition": "old_ssh_version",
            },
        ],
    },
    {
        "service": "smb",
        "ports": [139, 445],
        "tags": ["windows", "file_share"],
        "steps": [
            {
                "tool": "nmap",
                "args": {
                    "ports": "139,445",
                    "flags": "--script smb-vuln-*,smb-enum-shares",
                },
                "description": "SMB vulnerability and share enumeration",
            },
            {
                "tool": "metasploit",
                "args": {"module": "auxiliary/scanner/smb/smb_ms17_010"},
                "description": "EternalBlue check",
            },
            {"tool": "hydra", "args": {}, "description": "SMB credential brute force"},
        ],
    },
    {
        "service": "ftp",
        "ports": [21],
        "tags": ["file_transfer"],
        "steps": [
            {
                "tool": "nmap",
                "args": {
                    "ports": "21",
                    "flags": "--script ftp-anon,ftp-vsftpd-backdoor",
                },
                "description": "FTP anonymous login and vulnerability check",
            },
            {"tool": "hydra", "args": {}, "description": "FTP credential brute force"},
        ],
    },
    {
        "service": "mysql",
        "ports": [3306],
        "tags": ["database"],
        "steps": [
            {
                "tool": "nmap",
                "args": {"ports": "3306", "flags": "--script mysql-info,mysql-enum"},
                "description": "MySQL version and user enumeration",
            },
            {
                "tool": "hydra",
                "args": {},
                "description": "MySQL credential brute force",
            },
        ],
    },
    {
        "service": "rdp",
        "ports": [3389],
        "tags": ["remote_access", "windows"],
        "steps": [
            {
                "tool": "nmap",
                "args": {"ports": "3389", "flags": "--script rdp-vuln-ms12-020"},
                "description": "RDP vulnerability check (BlueKeep, MS12-020)",
            },
            {"tool": "hydra", "args": {}, "description": "RDP credential brute force"},
        ],
    },
    {
        "service": "wordpress",
        "ports": [80, 443],
        "tags": ["web", "cms"],
        "steps": [
            {
                "tool": "wpscan",
                "args": {},
                "description": "WordPress enumeration (plugins, themes, users)",
            },
            {
                "tool": "nuclei",
                "args": {"tags": "wordpress"},
                "description": "WordPress-specific vulnerability scan",
            },
            {
                "tool": "hydra",
                "args": {},
                "description": "WordPress admin brute force",
                "condition": "wp_admin_found",
            },
        ],
    },
]


class PlaybookEngine:
    """
    Matches discovered services to known attack playbooks.

    This provides deterministic, grounded recommendations instead of
    relying on LLM to hallucinate tool names and arguments.
    """

    _PATTERNS_FILE = data_path("cache", "exploit_patterns.json")

    def __init__(self, custom_playbook_dir: str | Path | None = None, patterns_file: str | Path | None = None):
        self.playbooks: list[ServicePlaybook] = []
        self.exploit_patterns: list[ExploitPattern] = []
        self._service_index: dict[str, int] = {}
        self._port_index: dict[int, int] = {}
        if patterns_file is not None:
            self._PATTERNS_FILE = Path(patterns_file)
        self._load_defaults()
        self._load_patterns()
        if custom_playbook_dir:
            self._load_custom(Path(custom_playbook_dir))
        self._rebuild_indices()

    def _rebuild_indices(self) -> None:
        """Rebuild lookup indices for $O(1)$ playbook discovery."""
        self._service_index = {}
        self._port_index = {}

        for i, pb in enumerate(self.playbooks):
            service_lower = pb.service.lower()
            if service_lower not in self._service_index:
                self._service_index[service_lower] = i

            for port in pb.ports:
                if port not in self._port_index:
                    self._port_index[port] = i

    def _load_defaults(self) -> None:
        """Load built-in playbooks."""
        for pb_data in DEFAULT_PLAYBOOKS:
            try:
                steps = [PlaybookStep(**s) for s in pb_data.get("steps", [])]
                pb = ServicePlaybook(
                    service=pb_data["service"],
                    ports=pb_data.get("ports", []),
                    steps=steps,
                    tags=pb_data.get("tags", []),
                )
                self.playbooks.append(pb)
            except (ValueError, TypeError, KeyError) as e:
                logger.warning("Failed to load playbook: %s", e)

        logger.info("Loaded %d default playbooks", len(self.playbooks))

    def _load_patterns(self) -> None:
        """Load persisted exploit patterns from disk."""
        try:
            if self._PATTERNS_FILE.exists():
                data = json.loads(self._PATTERNS_FILE.read_text())
                self.exploit_patterns = [ExploitPattern(**p) for p in data]
                logger.info("Loaded %d exploit patterns from disk", len(self.exploit_patterns))
        except (OSError, ValueError) as e:
            logger.warning("Failed to load exploit patterns: %s", e)

    def _save_patterns(self) -> None:
        """Atomically persist exploit patterns to disk."""
        tmp = self._PATTERNS_FILE.with_suffix(".tmp")
        try:
            self._PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(
                [p.model_dump() for p in self.exploit_patterns],
                indent=2,
                default=str,
            ))
            tmp.rename(self._PATTERNS_FILE)
        except (OSError, ValueError) as e:
            logger.warning("Failed to save exploit patterns: %s", e)
            if tmp.exists():
                tmp.unlink()

    def _load_custom(self, directory: Path) -> None:
        """Load custom playbooks from a directory."""
        if not directory.exists():
            return

        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    for item in data:
                        steps = [PlaybookStep(**s) for s in item.get("steps", [])]
                        pb = ServicePlaybook(
                            service=item["service"],
                            ports=item.get("ports", []),
                            steps=steps,
                            tags=item.get("tags", []),
                        )
                        self.playbooks.append(pb)
                logger.info("Loaded custom playbook from %s", path.name)
            except (OSError, ValueError, KeyError) as e:
                logger.warning("Failed to load custom playbook %s: %s", path, e)

    def add_playbook(self, playbook: ServicePlaybook) -> None:
        """Add a dynamic playbook to the engine and rebuild indices."""
        self.playbooks.append(playbook)
        self._rebuild_indices()

    def get_playbook_for_service(
        self, service: str, port: int | None = None
    ) -> ServicePlaybook | None:
        """Find matching playbook for a service.

        Optimized to use O(1) dictionary lookups instead of O(N) list traversal.
        Preserves original 'first-match-wins' priority by taking the minimum
        index when both service and port matches are found.
        """
        service_lower = service.lower()

        # O(1) lookups
        svc_idx = self._service_index.get(service_lower)

        if port is not None:
            port_idx = self._port_index.get(port)
            if svc_idx is None:
                if port_idx is None:
                    return None
                return self.playbooks[port_idx]
            if port_idx is None:
                return self.playbooks[svc_idx]

            # Both match, return the highest priority (lowest index)
            # to preserve original first-match-wins behavior
            best_idx = min(svc_idx, port_idx)
            return self.playbooks[best_idx]

        else:
            if svc_idx is None:
                return None
            return self.playbooks[svc_idx]

    def get_recommended_tools(
        self,
        services: list[dict[str, Any]],
        tools_already_run: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get tool recommendations based on discovered services.

        Returns a prioritized list of tool suggestions with reasoning
        grounded in the actual discovered services (not hallucinated).
        """
        already_run = set(tools_already_run or [])
        seen_tools = set()
        unique_recs = []

        for svc in services:
            service_name = svc.get("service", "").lower()
            port = svc.get("port")
            product = svc.get("product", "")

            playbook = self.get_playbook_for_service(service_name, port)
            if not playbook:
                continue

            for step in playbook.steps:
                # Performance Optimization: Skip already recommended or run tools
                # to prevent allocating dictionaries and filtering later
                if step.tool in already_run or step.tool in seen_tools:
                    continue

                seen_tools.add(step.tool)
                unique_recs.append(
                    {
                        "tool": step.tool,
                        "reason": f"{step.description} (service: {service_name} on port {port})",
                        "args": step.args,
                        "service_context": {
                            "service": service_name,
                            "port": port,
                            "product": product,
                        },
                        "playbook": playbook.service,
                    }
                )

        return unique_recs

    def record_success(
        self,
        service: str,
        tool: str,
        product: str | None = None,
        version: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> None:
        """Record a successful exploit pattern for learning."""
        from datetime import datetime

        existing = next(
            (
                p
                for p in self.exploit_patterns
                if p.service == service and p.tool == tool
            ),
            None,
        )

        if existing:
            existing.success_rate = min(existing.success_rate + 0.1, 1.0)
            existing.last_used = datetime.now().isoformat()
        else:
            self.exploit_patterns.append(
                ExploitPattern(
                    service=service,
                    product=product,
                    tool=tool,
                    args=args or {},
                    success_rate=0.5,
                    last_used=datetime.now().isoformat(),
                )
            )

        self._save_patterns()

    def get_grounded_prompt_context(
        self,
        services: list[dict[str, Any]],
        tools_already_run: list[str] | None = None,
    ) -> str:
        """
        Build a grounded context string for LLM prompts.

        Instead of relying on RAG similarity search, this provides
        deterministic, structured recommendations that the LLM can
        use to make better decisions.
        """
        recs = self.get_recommended_tools(services, tools_already_run)

        if not recs:
            return ""

        lines = ["**Playbook Recommendations** (based on confirmed services):"]
        for i, rec in enumerate(recs[:8], 1):
            lines.append(f"{i}. **{rec['tool']}**: {rec['reason']}")
            if rec.get("args"):
                lines.append(f"   Suggested args: {rec['args']}")

        return "\n".join(lines)


# Singleton
_engine: PlaybookEngine | None = None


def get_playbook_engine() -> PlaybookEngine:
    """Get the global PlaybookEngine instance."""
    global _engine
    if _engine is None:
        _engine = PlaybookEngine()
    return _engine
