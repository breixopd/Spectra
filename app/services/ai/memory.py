"""
Persistent Mission Memory — Learn from every engagement.

Stores structured lessons from past missions as JSON on disk.
No RAG, no embeddings, no Redis — just deterministic pattern matching
that gets more useful with every mission.

What it remembers:
- Which tools worked for which services/versions
- Which exploits succeeded against which targets
- OS fingerprints and what strategies worked per OS
- Tool argument combinations that produced results
- Common false positives to skip

How it's used:
- On mission start: load relevant lessons into agent prompts
- On tool success: record what worked
- On exploit success: record the full chain
- On mission end: persist everything to disk
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("spectra.ai.memory")

MEMORY_DIR = Path("reports/memory")


class ToolLesson(BaseModel):
    """What we learned from running a tool."""

    tool_id: str
    target_service: str
    target_product: str | None = None
    target_version: str | None = None
    target_os: str | None = None
    args_used: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    findings_count: int = 0
    finding_types: list[str] = Field(default_factory=list)
    notes: str = ""
    timestamp: str = ""


class ExploitLesson(BaseModel):
    """A successful exploit chain to remember."""

    target_service: str
    target_product: str | None = None
    target_version: str | None = None
    target_os: str | None = None
    exploit_tool: str
    exploit_args: dict[str, Any] = Field(default_factory=dict)
    payload_type: str | None = None
    access_level: str = "unknown"
    attack_chain: list[str] = Field(default_factory=list)
    cve_id: str | None = None
    timestamp: str = ""


class TargetProfile(BaseModel):
    """Learned profile for a target type."""

    os_family: str  # linux, windows, macos, freebsd, embedded, unknown
    os_version: str | None = None
    arch: str | None = None
    services: list[str] = Field(default_factory=list)
    effective_tools: list[str] = Field(default_factory=list)
    ineffective_tools: list[str] = Field(default_factory=list)
    effective_exploits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MissionMemory:
    """
    Persistent learning system that improves with every mission.

    Stores lessons as JSON files in reports/memory/:
    - tool_lessons.json — which tools work for which services
    - exploit_lessons.json — successful exploit chains
    - target_profiles.json — OS-specific strategies
    - false_positives.json — findings to skip
    """

    def __init__(self, memory_dir: Path | str = MEMORY_DIR):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.tool_lessons: list[ToolLesson] = []
        self.exploit_lessons: list[ExploitLesson] = []
        self.target_profiles: dict[str, TargetProfile] = {}
        self.false_positives: set[str] = set()

        self._load()

    def _load(self) -> None:
        """Load all memory from disk."""
        self.tool_lessons = self._load_file("tool_lessons.json", ToolLesson)
        self.exploit_lessons = self._load_file("exploit_lessons.json", ExploitLesson)
        self.false_positives = set(self._load_raw("false_positives.json") or [])

        profiles_raw = self._load_raw("target_profiles.json") or {}
        for key, data in profiles_raw.items():
            try:
                self.target_profiles[key] = TargetProfile(**data)
            except Exception:
                pass

        logger.info(
            "Loaded memory: %d tool lessons, %d exploit lessons, %d profiles, %d false positives",
            len(self.tool_lessons),
            len(self.exploit_lessons),
            len(self.target_profiles),
            len(self.false_positives),
        )

    def _load_file(self, filename: str, model_cls: type) -> list:
        """Load a list of Pydantic models from a JSON file."""
        path = self.memory_dir / filename
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return [model_cls(**item) for item in data if isinstance(item, dict)]
        except Exception as e:
            logger.warning("Failed to load %s: %s", filename, e)
            return []

    def _load_raw(self, filename: str) -> Any:
        """Load raw JSON data."""
        path = self.memory_dir / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save(self) -> None:
        """Persist all memory to disk."""
        self._save_file(
            "tool_lessons.json",
            [l.model_dump() for l in self.tool_lessons[-500:]],
        )
        self._save_file(
            "exploit_lessons.json",
            [l.model_dump() for l in self.exploit_lessons[-200:]],
        )
        self._save_file(
            "target_profiles.json",
            {k: v.model_dump() for k, v in self.target_profiles.items()},
        )
        self._save_file("false_positives.json", list(self.false_positives))

    def _save_file(self, filename: str, data: Any) -> None:
        """Save data to a JSON file atomically."""
        path = self.memory_dir / filename
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.rename(path)
        except Exception as e:
            logger.warning("Failed to save %s: %s", filename, e)
            if tmp.exists():
                tmp.unlink()

    # --- Recording Lessons ---

    def record_tool_result(
        self,
        tool_id: str,
        target_service: str,
        success: bool,
        findings_count: int = 0,
        finding_types: list[str] | None = None,
        target_product: str | None = None,
        target_version: str | None = None,
        target_os: str | None = None,
        args_used: dict[str, Any] | None = None,
    ) -> None:
        """Record what happened when we ran a tool."""
        self.tool_lessons.append(
            ToolLesson(
                tool_id=tool_id,
                target_service=target_service,
                target_product=target_product,
                target_version=target_version,
                target_os=target_os,
                args_used=args_used or {},
                success=success,
                findings_count=findings_count,
                finding_types=finding_types or [],
                timestamp=datetime.now().isoformat(),
            )
        )
        self._save()

    def record_exploit_success(
        self,
        target_service: str,
        exploit_tool: str,
        attack_chain: list[str] | None = None,
        target_product: str | None = None,
        target_version: str | None = None,
        target_os: str | None = None,
        exploit_args: dict[str, Any] | None = None,
        payload_type: str | None = None,
        access_level: str = "unknown",
        cve_id: str | None = None,
    ) -> None:
        """Record a successful exploit for future reference."""
        self.exploit_lessons.append(
            ExploitLesson(
                target_service=target_service,
                target_product=target_product,
                target_version=target_version,
                target_os=target_os,
                exploit_tool=exploit_tool,
                exploit_args=exploit_args or {},
                payload_type=payload_type,
                access_level=access_level,
                attack_chain=attack_chain or [],
                cve_id=cve_id,
                timestamp=datetime.now().isoformat(),
            )
        )
        self._save()

    def record_false_positive(self, template_id: str) -> None:
        """Mark a finding template as a known false positive."""
        self.false_positives.add(template_id)
        self._save()

    def update_target_profile(
        self,
        os_family: str,
        os_version: str | None = None,
        effective_tools: list[str] | None = None,
        ineffective_tools: list[str] | None = None,
        effective_exploits: list[str] | None = None,
        services: list[str] | None = None,
        note: str | None = None,
    ) -> None:
        """Update knowledge about a target OS type."""
        key = os_family.lower()
        if key not in self.target_profiles:
            self.target_profiles[key] = TargetProfile(os_family=key)

        profile = self.target_profiles[key]
        if os_version:
            profile.os_version = os_version
        if effective_tools:
            for t in effective_tools:
                if t not in profile.effective_tools:
                    profile.effective_tools.append(t)
        if ineffective_tools:
            for t in ineffective_tools:
                if t not in profile.ineffective_tools:
                    profile.ineffective_tools.append(t)
        if effective_exploits:
            for e in effective_exploits:
                if e not in profile.effective_exploits:
                    profile.effective_exploits.append(e)
        if services:
            for s in services:
                if s not in profile.services:
                    profile.services.append(s)
        if note:
            profile.notes.append(note)

        self._save()

    # --- Querying Lessons ---

    def get_tool_recommendations(
        self,
        service: str,
        product: str | None = None,
        os_family: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get tool recommendations based on past experience."""
        recommendations = []
        seen_tools = set()

        for lesson in reversed(self.tool_lessons):
            if lesson.tool_id in seen_tools:
                continue

            if lesson.target_service.lower() != service.lower():
                continue

            if not lesson.success or lesson.findings_count == 0:
                continue

            relevance = 0.5
            if (
                product
                and lesson.target_product
                and product.lower() in lesson.target_product.lower()
            ):
                relevance += 0.3
            if (
                os_family
                and lesson.target_os
                and os_family.lower() in lesson.target_os.lower()
            ):
                relevance += 0.2

            recommendations.append(
                {
                    "tool": lesson.tool_id,
                    "reason": f"Previously found {lesson.findings_count} findings on {lesson.target_service}"
                    + (f" ({lesson.target_product})" if lesson.target_product else ""),
                    "args": lesson.args_used,
                    "relevance": relevance,
                    "finding_types": lesson.finding_types,
                }
            )
            seen_tools.add(lesson.tool_id)

        recommendations.sort(key=lambda x: x["relevance"], reverse=True)
        return recommendations[:5]

    def get_exploit_history(
        self,
        service: str | None = None,
        product: str | None = None,
    ) -> list[ExploitLesson]:
        """Get past successful exploits for a service/product."""
        results = []
        for lesson in reversed(self.exploit_lessons):
            if service and lesson.target_service.lower() != service.lower():
                continue
            if (
                product
                and lesson.target_product
                and product.lower() not in lesson.target_product.lower()
            ):
                continue
            results.append(lesson)
            if len(results) >= 5:
                break
        return results

    def get_os_strategy(self, os_family: str) -> TargetProfile | None:
        """Get learned strategy for an OS type."""
        return self.target_profiles.get(os_family.lower())

    def is_false_positive(self, template_id: str) -> bool:
        """Check if a finding template is a known false positive."""
        return template_id in self.false_positives

    def get_context_for_prompt(
        self,
        service: str | None = None,
        product: str | None = None,
        os_family: str | None = None,
    ) -> str:
        """
        Build a context string from memory for injection into agent prompts.

        This is the key integration point — agents get smarter over time
        because this context grows with each mission.
        """
        parts = []

        # Tool recommendations from past experience
        if service:
            recs = self.get_tool_recommendations(service, product, os_family)
            if recs:
                lines = ["**Past Experience** (from previous missions):"]
                for r in recs[:3]:
                    lines.append(f"  - {r['tool']}: {r['reason']}")
                    if r.get("args"):
                        lines.append(f"    Effective args: {r['args']}")
                parts.append("\n".join(lines))

        # Exploit history
        if service:
            exploits = self.get_exploit_history(service, product)
            if exploits:
                lines = ["**Successful Exploits** (from previous missions):"]
                for ex in exploits[:3]:
                    chain_str = (
                        " → ".join(ex.attack_chain)
                        if ex.attack_chain
                        else ex.exploit_tool
                    )
                    lines.append(
                        f"  - {chain_str}"
                        + (f" (CVE: {ex.cve_id})" if ex.cve_id else "")
                        + f" → {ex.access_level} access"
                    )
                parts.append("\n".join(lines))

        # OS-specific strategy
        if os_family:
            profile = self.get_os_strategy(os_family)
            if profile:
                lines = [f"**{os_family.title()} Strategy** (learned):"]
                if profile.effective_tools:
                    lines.append(
                        f"  Effective tools: {', '.join(profile.effective_tools)}"
                    )
                if profile.ineffective_tools:
                    lines.append(
                        f"  Skip these tools: {', '.join(profile.ineffective_tools)}"
                    )
                if profile.effective_exploits:
                    lines.append(
                        f"  Known exploits: {', '.join(profile.effective_exploits)}"
                    )
                if profile.notes:
                    lines.append(f"  Notes: {profile.notes[-1]}")
                parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        return {
            "tool_lessons": len(self.tool_lessons),
            "exploit_lessons": len(self.exploit_lessons),
            "target_profiles": len(self.target_profiles),
            "false_positives": len(self.false_positives),
            "profiles": list(self.target_profiles.keys()),
        }


# --- OS Detection ---

OS_SIGNATURES = {
    "linux": [
        "Linux",
        "Ubuntu",
        "Debian",
        "CentOS",
        "RedHat",
        "Fedora",
        "Kali",
        "Alpine",
        "Arch",
        "SUSE",
        "Gentoo",
        "Mint",
    ],
    "windows": [
        "Windows",
        "Microsoft",
        "IIS",
        "NTLM",
        "SMB",
        "Active Directory",
        "PowerShell",
        "Win32",
        "Win64",
        ".NET",
    ],
    "macos": ["macOS", "Darwin", "Apple", "OS X"],
    "freebsd": ["FreeBSD", "OpenBSD", "NetBSD", "pfSense"],
    "embedded": [
        "MikroTik",
        "Cisco",
        "Juniper",
        "FortiOS",
        "DD-WRT",
        "OpenWrt",
        "RTOS",
        "VxWorks",
        "firmware",
    ],
}


def detect_os_from_output(output: str) -> str:
    """Detect OS family from tool output (nmap banners, etc.)."""
    output_lower = output.lower()

    scores: dict[str, int] = {}
    for os_family, signatures in OS_SIGNATURES.items():
        score = sum(1 for sig in signatures if sig.lower() in output_lower)
        if score > 0:
            scores[os_family] = score

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)  # type: ignore[arg-type]


def detect_os_from_services(services: list[dict[str, Any]]) -> str:
    """Detect OS family from discovered services."""
    all_text = " ".join(
        f"{s.get('product', '')} {s.get('version', '')} {s.get('service', '')}"
        for s in services
    )
    return detect_os_from_output(all_text)


# --- Singleton ---

_memory: MissionMemory | None = None


def get_memory() -> MissionMemory:
    """Get the global MissionMemory instance."""
    global _memory
    if _memory is None:
        _memory = MissionMemory()
    return _memory
