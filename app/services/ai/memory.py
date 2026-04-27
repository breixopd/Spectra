"""
Persistent Mission Memory — Learn from every engagement.

Stores structured lessons from past missions as JSON on disk.
No RAG, no embeddings — just deterministic pattern matching
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

import contextlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.infrastructure.paths import data_path

logger = logging.getLogger(__name__)

MEMORY_DIR = data_path("cache")

# Files containing potentially sensitive data (exploit chains, credentials)
_ENCRYPTED_FILES: frozenset[str] = frozenset({"exploit_lessons.json"})


def _memory_dir_for_user(user_id: str | None) -> Path:
    if not user_id:
        return MEMORY_DIR
    return MEMORY_DIR / "users" / user_id


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

    Stores lessons as JSON files in data/cache/:
    - tool_lessons.json — which tools work for which services
    - exploit_lessons.json — successful exploit chains
    - target_profiles.json — OS-specific strategies
    - false_positives.json — findings to skip
    """

    MAX_BACKUPS = 5

    def __init__(self, memory_dir: Path | str = MEMORY_DIR):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.tool_lessons: list[ToolLesson] = []
        self.exploit_lessons: list[ExploitLesson] = []
        self.target_profiles: dict[str, TargetProfile] = {}
        self.false_positives: set[str] = set()

        # In-memory indexes for fast lookups (MEM-002)
        self._tool_index: dict[str, list[int]] = {}
        self._service_index: dict[str, list[int]] = {}

        # Debounce saves: skip if <5s since last save
        self._last_save_time: float = 0.0
        self._dirty: bool = False

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
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Failed to load target profile: %s", e)

        self._rebuild_indexes()

        logger.info(
            "Loaded memory: %d tool lessons, %d exploit lessons, %d profiles, %d false positives",
            len(self.tool_lessons),
            len(self.exploit_lessons),
            len(self.target_profiles),
            len(self.false_positives),
        )

    def _rebuild_indexes(self) -> None:
        """Rebuild in-memory indexes from tool_lessons."""
        self._tool_index.clear()
        self._service_index.clear()
        for i, lesson in enumerate(self.tool_lessons):
            self._tool_index.setdefault(lesson.tool_id, []).append(i)
            svc_key = lesson.target_service.lower()
            self._service_index.setdefault(svc_key, []).append(i)

    def _index_tool_lesson(self, index: int, lesson: ToolLesson) -> None:
        """Add a single lesson to the indexes."""
        self._tool_index.setdefault(lesson.tool_id, []).append(index)
        svc_key = lesson.target_service.lower()
        self._service_index.setdefault(svc_key, []).append(index)

    def _load_file(self, filename: str, model_cls: type) -> list:
        """Load a list of Pydantic models from a JSON file, falling back to backups."""
        path = self.memory_dir / filename
        if not path.exists():
            # Try loading from backup
            return self._load_with_fallback(filename, model_cls)
        try:
            raw = self._read_maybe_encrypted(path, filename)
            data = json.loads(raw)
            return [model_cls(**item) for item in data if isinstance(item, dict)]
        except (OSError, ValueError) as e:
            logger.warning("Failed to load %s: %s — trying backups", filename, e)
            return self._load_with_fallback(filename, model_cls)

    def _read_maybe_encrypted(self, path: Path, filename: str) -> str:
        """Read a file, decrypting it if it's in the encrypted set."""
        if filename in _ENCRYPTED_FILES:
            try:
                from app.auth.encryption import decrypt_file
                return decrypt_file(path).decode("utf-8")
            except Exception:
                # Fall back to plaintext (pre-encryption data or missing key)
                pass
        return path.read_text()

    def _load_raw(self, filename: str) -> Any:
        """Load raw JSON data."""
        path = self.memory_dir / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            # Try backups for raw files too
            for i in range(1, self.MAX_BACKUPS + 1):
                bak = self.memory_dir / f"{filename}.{i}.bak"
                if bak.exists():
                    try:
                        return json.loads(bak.read_text())
                    except (OSError, ValueError):
                        continue
            return None

    def _load_with_fallback(self, filename: str, model_cls: type) -> list:
        """Try loading from backup files when primary fails."""
        for i in range(1, self.MAX_BACKUPS + 1):
            bak = self.memory_dir / f"{filename}.{i}.bak"
            if bak.exists():
                try:
                    data = json.loads(bak.read_text())
                    logger.info("Recovered %s from backup %d", filename, i)
                    return [model_cls(**item) for item in data if isinstance(item, dict)]
                except (OSError, ValueError):
                    continue
        return []

    def _rotate_backup(self, filepath: Path) -> None:
        """Rotate backup files before writing. Keeps last MAX_BACKUPS copies."""
        if not filepath.exists():
            return
        # Shift existing backups: .4.bak -> .5.bak, .3.bak -> .4.bak, etc.
        for i in range(self.MAX_BACKUPS, 1, -1):
            older = filepath.parent / f"{filepath.name}.{i}.bak"
            newer = filepath.parent / f"{filepath.name}.{i - 1}.bak"
            if newer.exists():
                with contextlib.suppress(OSError):
                    newer.rename(older)
        # Current file becomes .1.bak
        bak1 = filepath.parent / f"{filepath.name}.1.bak"
        try:
            # Copy content rather than rename, so the original stays for atomic write
            bak1.write_bytes(filepath.read_bytes())
        except OSError as e:
            logger.warning("Backup rotation failed for %s: %s", filepath.name, e)

    def _save(self) -> None:
        """Persist all memory to disk with time-based debounce."""
        now = time.monotonic()
        if now - self._last_save_time < 5:
            self._dirty = True
            return
        self._dirty = False
        self._last_save_time = now
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

    def force_save(self) -> None:
        """Flush pending changes to disk immediately."""
        if self._dirty:
            self._dirty = False
            self._last_save_time = time.monotonic()
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
        """Save data to a JSON file atomically with backup rotation.

        Files listed in _ENCRYPTED_FILES are encrypted at rest.
        """
        path = self.memory_dir / filename
        self._rotate_backup(path)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, default=str))
            if filename in _ENCRYPTED_FILES:
                try:
                    from app.auth.encryption import encrypt_file
                    encrypt_file(tmp)
                except Exception as e:
                    logger.warning("Failed to encrypt %s (saving plaintext): %s", filename, e)
            tmp.rename(path)
        except OSError as e:
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
        lesson = ToolLesson(
            tool_id=tool_id,
            target_service=target_service,
            target_product=target_product,
            target_version=target_version,
            target_os=target_os,
            args_used=args_used or {},
            success=success,
            findings_count=findings_count,
            finding_types=finding_types or [],
            timestamp=datetime.now(UTC).isoformat(),
        )
        # Deduplicate: update existing entry if same tool+service+product+outcome
        deduplicated = False
        for existing in self.tool_lessons:
            if (
                existing.tool_id == lesson.tool_id
                and existing.target_service == lesson.target_service
                and existing.target_product == lesson.target_product
                and existing.success == lesson.success
            ):
                existing.findings_count = max(existing.findings_count, lesson.findings_count)
                existing.timestamp = lesson.timestamp
                existing.success = lesson.success
                deduplicated = True
                break
        if not deduplicated:
            idx = len(self.tool_lessons)
            self.tool_lessons.append(lesson)
            self._index_tool_lesson(idx, lesson)
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
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        self._save()

    def record_false_positive(self, template_id: str) -> None:
        """Mark a finding template as a known false positive."""
        self.false_positives.add(template_id)
        self._save()

    def record_tool_lesson(self, tool: str, lesson: str, context: str = "") -> None:
        """Record a freeform lesson (e.g. from debrief) as a ToolLesson note."""
        entry = ToolLesson(
            tool_id=tool,
            target_service=context,
            success=True,
            notes=lesson,
            timestamp=datetime.now(UTC).isoformat(),
        )
        idx = len(self.tool_lessons)
        self.tool_lessons.append(entry)
        self._index_tool_lesson(idx, entry)
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

    def get_lessons_for_tool(self, tool_id: str) -> list[ToolLesson]:
        """Get all lessons for a specific tool using the index."""
        indices = self._tool_index.get(tool_id, [])
        return [self.tool_lessons[i] for i in indices if i < len(self.tool_lessons)]

    def get_lessons_for_service(self, service: str) -> list[ToolLesson]:
        """Get all lessons for a specific service using the index."""
        indices = self._service_index.get(service.lower(), [])
        return [self.tool_lessons[i] for i in indices if i < len(self.tool_lessons)]

    def get_tool_recommendations(
        self,
        service: str,
        product: str | None = None,
        os_family: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get tool recommendations based on past experience."""
        recommendations = []
        seen_tools: set[str] = set()

        # Use service index for faster lookup instead of scanning all lessons
        service_indices = self._service_index.get(service.lower(), [])
        for idx in reversed(service_indices):
            if idx >= len(self.tool_lessons):
                continue
            lesson = self.tool_lessons[idx]
            if lesson.tool_id in seen_tools:
                continue

            if lesson.tool_id != "debrief" and (not lesson.success or lesson.findings_count == 0):
                continue

            relevance = 0.5
            if product and lesson.target_product and product.lower() in lesson.target_product.lower():
                relevance += 0.3
            if os_family and lesson.target_os and os_family.lower() in lesson.target_os.lower():
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
            if product and lesson.target_product and product.lower() not in lesson.target_product.lower():
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
        # Flush any pending saves before reading
        self.force_save()

        if not service and not product and not os_family:
            sections = []
            # Top tools by frequency
            tool_counts: dict[str, int] = {}
            for lesson in self.tool_lessons[-100:]:
                tid = lesson.tool_id
                if tid and tid != "debrief":
                    tool_counts[tid] = tool_counts.get(tid, 0) + 1
            if tool_counts:
                top = sorted(tool_counts.items(), key=lambda x: -x[1])[:3]
                sections.append("Most effective tools: " + ", ".join(f"{t}({c} uses)" for t, c in top))
            # Recent exploit successes
            recent_exploits = self.exploit_lessons[-3:]
            if recent_exploits:
                names = [e.exploit_tool for e in recent_exploits]
                sections.append("Recent successful exploits: " + ", ".join(names))
            return "\n".join(sections) if sections else ""

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
                    chain_str = " → ".join(ex.attack_chain) if ex.attack_chain else ex.exploit_tool
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
                    lines.append(f"  Effective tools: {', '.join(profile.effective_tools)}")
                if profile.ineffective_tools:
                    lines.append(f"  Skip these tools: {', '.join(profile.ineffective_tools)}")
                if profile.effective_exploits:
                    lines.append(f"  Known exploits: {', '.join(profile.effective_exploits)}")
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

    def aggregate_knowledge(self) -> dict[str, Any]:
        """Aggregate cross-mission knowledge by (tool_id, service)."""
        from collections import defaultdict

        combos: dict[tuple[str, str], list[ToolLesson]] = defaultdict(list)
        for lesson in self.tool_lessons:
            key = (lesson.tool_id, lesson.target_service.lower())
            combos[key].append(lesson)

        service_profiles: dict[str, dict[str, Any]] = {}
        for (tool_id, service), lessons in combos.items():
            svc_key = service
            if svc_key not in service_profiles:
                service_profiles[svc_key] = {
                    "best_tools": [],
                    "common_findings": [],
                    "success_rate": {},
                    "total_assessments": 0,
                }

            total = len(lessons)
            successes = sum(1 for l in lessons if l.success and l.findings_count > 0)
            rate = successes / total if total > 0 else 0.0

            profile = service_profiles[svc_key]
            profile["success_rate"][tool_id] = round(rate, 2)
            profile["total_assessments"] += total

            if rate > 0.5 and tool_id not in profile["best_tools"]:
                profile["best_tools"].append(tool_id)

            for lesson in lessons:
                for ft in lesson.finding_types:
                    if ft not in profile["common_findings"]:
                        profile["common_findings"].append(ft)

        result = {
            "service_profiles": service_profiles,
            "last_aggregated": datetime.now(UTC).isoformat(),
        }

        # Persist aggregated knowledge
        output_dir = data_path("cache")
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            out_path = output_dir / "aggregated_knowledge.json"
            out_path.write_text(json.dumps(result, indent=2, default=str))
        except OSError as e:
            logger.warning("Failed to save aggregated knowledge: %s", e)

        return result


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

# Performance Optimization: Pre-compute lowercase signatures to avoid recalculating
# them inside the hot path during output matching.
OS_SIGNATURES_LOWER: dict[str, list[str]] = {
    os_family: [sig.lower() for sig in signatures] for os_family, signatures in OS_SIGNATURES.items()
}


def detect_os_from_output(output: str) -> str:
    """Detect OS family from tool output (nmap banners, etc.)."""
    output_lower = output.lower()

    scores: dict[str, int] = {}
    for os_family, signatures in OS_SIGNATURES_LOWER.items():
        score = sum(1 for sig in signatures if sig in output_lower)
        if score > 0:
            scores[os_family] = score

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)  # type: ignore[arg-type]


def detect_os_from_services(services: list[dict[str, Any]]) -> str:
    """Detect OS family from discovered services."""
    all_text = " ".join(f"{s.get('product', '')} {s.get('version', '')} {s.get('service', '')}" for s in services)
    return detect_os_from_output(all_text)


# --- Singleton ---

_memory: MissionMemory | None = None
_memory_by_user: dict[str, MissionMemory] = {}


def get_memory(user_id: str | None = None) -> MissionMemory:
    """Get the mission memory instance, scoped per user when user_id is provided."""
    global _memory
    if user_id:
        memory = _memory_by_user.get(user_id)
        if memory is None:
            memory = MissionMemory(memory_dir=_memory_dir_for_user(user_id))
            _memory_by_user[user_id] = memory
        return memory
    if _memory is None:
        _memory = MissionMemory()
    return _memory
