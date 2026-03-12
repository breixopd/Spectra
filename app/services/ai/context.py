"""Context window management for LLM prompts."""

import hashlib
import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Context section priority — lower number = higher priority (kept first)."""

    CRITICAL = 0  # System prompt, task instruction
    HIGH = 1  # Current target/findings data, tool output
    MEDIUM = 2  # Memory lessons, playbook recommendations
    LOW = 3  # RAG context, methodology reference
    OPTIONAL = 4  # Historical stats, nice-to-have context


@dataclass
class ContextSection:
    """A section of context to include in a prompt."""

    name: str
    content: str
    priority: Priority
    max_tokens: int | None = None  # Optional per-section cap

    @property
    def token_estimate(self) -> int:
        return len(self.content) // ContextManager.CHARS_PER_TOKEN


class ContextManager:
    """Manages token budget across context sections for LLM prompts."""

    CHARS_PER_TOKEN = 4  # Conservative estimate

    def __init__(self, max_context_tokens: int = 6000):
        self.max_context_tokens = max_context_tokens

    def build(self, sections: list[ContextSection]) -> str:
        """Build a prompt from sections, respecting token budget.

        Sections are sorted by priority. Lower priority sections are
        truncated or dropped first when budget is exceeded.
        """
        sorted_sections = sorted(sections, key=lambda s: s.priority)

        result_parts: list[str] = []
        tokens_used = 0

        for section in sorted_sections:
            content = section.content
            if not content or not content.strip():
                continue

            section_tokens = len(content) // self.CHARS_PER_TOKEN

            # Apply per-section cap
            if section.max_tokens and section_tokens > section.max_tokens:
                max_chars = section.max_tokens * self.CHARS_PER_TOKEN
                content = content[:max_chars] + "\n[... truncated]"
                section_tokens = section.max_tokens

            # Check remaining budget
            remaining = self.max_context_tokens - tokens_used
            if section_tokens > remaining:
                if section.priority <= Priority.HIGH:
                    # High-priority: truncate to fit
                    max_chars = remaining * self.CHARS_PER_TOKEN
                    if max_chars > 100:
                        content = content[:max_chars] + "\n[... truncated]"
                        section_tokens = remaining
                    else:
                        continue
                else:
                    continue

            result_parts.append(content)
            tokens_used += section_tokens

        return "\n\n".join(result_parts)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count for text."""
        return len(text) // ContextManager.CHARS_PER_TOKEN


def truncate_for_llm(text: str, max_chars: int = 3000, label: str = "output") -> str:
    """Truncate text for LLM context, keeping head and tail."""
    if not text or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n[... {len(text) - max_chars} chars of {label} omitted ...]\n\n" + text[-half:]


def summarize_context(text: str, max_chars: int = 2000) -> str:
    """Compress long context by extracting key sections rather than blind truncation.

    Keeps structured data (bullet points, key=value pairs, headings) and
    drops verbose prose from the middle.
    """
    if not text or len(text) <= max_chars:
        return text

    lines = text.splitlines()
    scored: list[tuple[int, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            scored.append((0, line))
            continue
        score = 1
        # Headings and structure markers are high-value
        if stripped.startswith(("#", "[", "---", "===")):
            score = 4
        # Bullet points / key findings
        elif stripped.startswith(("-", "*", "•")):
            score = 3
        # Key-value or data lines
        elif ":" in stripped[:60] or "=" in stripped[:60]:
            score = 2
        scored.append((score, line))

    # Always keep first and last 10% of lines
    n = len(scored)
    keep_boundary = max(n // 10, 3)
    head = scored[:keep_boundary]
    tail = scored[-keep_boundary:]
    middle = scored[keep_boundary : n - keep_boundary]

    # Sort middle by score descending, take highest-value lines
    middle_sorted = sorted(middle, key=lambda x: x[0], reverse=True)

    result_lines = [line for _, line in head]
    budget = max_chars - sum(len(line) + 1 for line in result_lines)
    budget -= sum(len(line) + 1 for _, line in tail)
    budget -= 40  # Reserve for omission marker

    added_middle = []
    for _score, line in middle_sorted:
        if budget <= 0:
            break
        added_middle.append(line)
        budget -= len(line) + 1

    omitted = len(middle) - len(added_middle)
    if omitted > 0:
        result_lines.append(f"\n[... {omitted} lines summarized ...]\n")
    result_lines.extend(added_middle)
    result_lines.extend(line for _, line in tail)

    result = "\n".join(result_lines)
    # Final safety truncation
    if len(result) > max_chars:
        result = result[: max_chars - 20] + "\n[... truncated]"
    return result


@dataclass
class _CacheEntry:
    """Single entry in the agent output cache."""

    value: Any
    created_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl


class AgentOutputCache:
    """Simple TTL cache for agent LLM outputs to avoid redundant calls.

    Keys are derived from a hash of (agent_name, prompt_text) so identical
    requests within the TTL window return the cached result.
    """

    MAX_ENTRIES = 256

    def __init__(self, default_ttl: float = 300.0):
        self._store: dict[str, _CacheEntry] = {}
        self._default_ttl = default_ttl

    @staticmethod
    def _make_key(agent_name: str, prompt: str) -> str:
        raw = f"{agent_name}:{prompt}"
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]

    def get(self, agent_name: str, prompt: str) -> Any | None:
        key = self._make_key(agent_name, prompt)
        entry = self._store.get(key)
        if entry is None or entry.expired:
            self._store.pop(key, None)
            return None
        return entry.value

    def put(self, agent_name: str, prompt: str, value: Any, ttl: float | None = None) -> None:
        # Evict expired entries if we're at capacity
        if len(self._store) >= self.MAX_ENTRIES:
            expired_keys = [k for k, v in self._store.items() if v.expired]
            for k in expired_keys:
                del self._store[k]
            # If still full, evict oldest
            if len(self._store) >= self.MAX_ENTRIES:
                oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
                del self._store[oldest_key]

        key = self._make_key(agent_name, prompt)
        self._store[key] = _CacheEntry(
            value=value,
            created_at=time.monotonic(),
            ttl=ttl if ttl is not None else self._default_ttl,
        )

    def clear(self) -> None:
        self._store.clear()


# Global agent output cache
_agent_cache = AgentOutputCache()


def get_agent_cache() -> AgentOutputCache:
    """Return the global agent output cache."""
    return _agent_cache
