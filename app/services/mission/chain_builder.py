"""
Exploit Chain Builder — multi-stage attack execution with fallbacks.

Defines chains like:
  Exploit Web App → Get Shell → Dump Creds → Pivot to Internal → Exfil Data

Each stage has:
- Tool to run
- Success criteria (regex match on output)
- Fallback path (alternate stage if this one fails)
- Max retries
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.infrastructure.paths import data_path

logger = logging.getLogger(__name__)


class ChainStage(BaseModel):
    """A single stage in an exploit chain."""

    id: str
    name: str
    description: str = ""
    tool: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    success_regex: str | None = None  # regex to match on output for success
    failure_regex: str | None = None  # regex indicating definite failure
    fallback_stage: str | None = None  # stage ID to try if this fails
    max_retries: int = 1
    timeout: int = 300
    phase: str = "exploitation"


class ExploitChain(BaseModel):
    """A complete multi-stage exploit chain."""

    id: str
    name: str
    description: str = ""
    target: str = ""
    stages: list[ChainStage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChainExecutionResult(BaseModel):
    """Result of executing a chain."""

    chain_id: str
    success: bool = False
    stages_completed: int = 0
    stages_total: int = 0
    failed_stage: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    final_access_level: str = "none"


class ChainBuilder:
    """Builds and validates exploit chains."""

    @staticmethod
    def create_chain(name: str, stages: list[dict]) -> ExploitChain:
        """Create a chain from stage definitions."""
        chain_stages = [ChainStage(**s) for s in stages]
        return ExploitChain(
            id=f"chain-{name.lower().replace(' ', '-')}",
            name=name,
            stages=chain_stages,
        )

    @staticmethod
    def validate_chain(chain: ExploitChain) -> list[str]:
        """Validate chain for issues. Returns list of warnings."""
        warnings = []
        stage_ids = {s.id for s in chain.stages}

        for stage in chain.stages:
            if stage.fallback_stage and stage.fallback_stage not in stage_ids:
                warnings.append(f"Stage '{stage.id}': fallback '{stage.fallback_stage}' not found")
            if not stage.tool and not stage.description:
                warnings.append(f"Stage '{stage.id}': no tool or description")

        if not chain.stages:
            warnings.append("Chain has no stages")

        return warnings

    @staticmethod
    def check_stage_success(output: str, stage: ChainStage) -> bool:
        """Check if a stage succeeded based on output patterns."""
        if stage.success_regex:
            return bool(re.search(stage.success_regex, output, re.IGNORECASE))
        # If no success regex, consider non-empty output as success
        return bool(output.strip())

    @staticmethod
    def check_stage_failure(output: str, stage: ChainStage) -> bool:
        """Check if a stage definitively failed."""
        if stage.failure_regex:
            return bool(re.search(stage.failure_regex, output, re.IGNORECASE))
        return False


# Pre-built exploit chains
BUILTIN_CHAINS: list[dict[str, Any]] = [
    {
        "id": "chain-web-to-shell",
        "name": "Web App to Shell",
        "description": "Exploit web vulnerability to gain shell access",
        "stages": [
            {"id": "scan", "name": "Service Discovery", "tool": "nmap", "phase": "discovery", "success_regex": "open"},
            {
                "id": "vuln",
                "name": "Vulnerability Scan",
                "tool": "nuclei",
                "phase": "vulnerability",
                "success_regex": "critical|high",
            },
            {
                "id": "exploit",
                "name": "Exploit Vulnerability",
                "tool": "sqlmap",
                "phase": "exploitation",
                "success_regex": "injection|dumped",
                "fallback_stage": "brute",
            },
            {
                "id": "brute",
                "name": "Default Credentials",
                "tool": "hydra",
                "phase": "exploitation",
                "success_regex": "login:|password:",
            },
        ],
    },
    {
        "id": "chain-network-pivot",
        "name": "Network Pivot Chain",
        "description": "Gain access then enumerate internal network",
        "stages": [
            {"id": "scan", "name": "Port Scan", "tool": "nmap", "phase": "discovery", "success_regex": "open"},
            {
                "id": "enum",
                "name": "Service Enumeration",
                "tool": "nuclei",
                "phase": "enumeration",
                "success_regex": "template-id",
            },
            {"id": "exploit", "name": "Initial Access", "phase": "exploitation", "success_regex": "session|shell"},
            {
                "id": "internal",
                "name": "Internal Recon",
                "phase": "post_exploitation",
                "success_regex": "192\\.168|10\\.0|172\\.16",
            },
        ],
    },
]


def get_builtin_chains() -> list[ExploitChain]:
    """Get all built-in exploit chains."""
    chains = []
    for chain_data in BUILTIN_CHAINS:
        stages = [ChainStage(**s) for s in chain_data.get("stages", [])]
        chains.append(
            ExploitChain(
                id=chain_data["id"],
                name=chain_data["name"],
                description=chain_data.get("description", ""),
                stages=stages,
            )
        )
    return chains


CUSTOM_CHAINS_PATH = data_path("cache", "custom_chains.json")


def load_custom_chains() -> list[ExploitChain]:
    """Load user-created exploit chains from disk."""
    if not CUSTOM_CHAINS_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_CHAINS_PATH.read_text())
        chains = []
        for item in data:
            stages = [ChainStage(**s) for s in item.get("stages", [])]
            chains.append(
                ExploitChain(
                    id=item["id"],
                    name=item["name"],
                    description=item.get("description", ""),
                    stages=stages,
                    metadata=item.get("metadata", {}),
                )
            )
        return chains
    except (OSError, ValueError, KeyError) as e:
        logger.warning("Failed to load custom chains: %s", e)
        return []


def save_custom_chain(chain: ExploitChain) -> None:
    """Append a custom chain to disk storage."""
    existing = load_custom_chains()
    existing.append(chain)
    CUSTOM_CHAINS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_CHAINS_PATH.write_text(json.dumps([c.model_dump() for c in existing], indent=2, default=str))
