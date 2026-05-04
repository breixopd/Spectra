"""Context window management for LLM prompts."""

import logging
from dataclasses import dataclass
from enum import IntEnum

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
        return ContextManager.estimate_tokens(self.content)


class ContextManager:
    """Manages token budget across context sections for LLM prompts."""

    CHARS_PER_TOKEN = 3.5  # Conservative estimate (closer to reality for code/JSON)

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

            section_tokens = self.estimate_tokens(content)

            # Apply per-section cap
            if section.max_tokens and section_tokens > section.max_tokens:
                max_chars = int(section.max_tokens * self.CHARS_PER_TOKEN)
                content = content[:max_chars] + "\n[... truncated]"
                section_tokens = section.max_tokens

            # Check remaining budget
            remaining = self.max_context_tokens - tokens_used
            if section_tokens > remaining:
                if section.priority <= Priority.HIGH:
                    # High-priority: truncate to fit
                    max_chars = int(remaining * self.CHARS_PER_TOKEN)
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
        """Estimate token count using character-based heuristic (~3.5 chars per token)."""
        return max(1, len(text) * 10 // 35)


def truncate_for_llm(text: str, max_chars: int = 3000, label: str = "output") -> str:
    """Truncate text for LLM context, keeping head and tail."""
    if not text or len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n[... {len(text) - max_chars} chars of {label} omitted ...]\n\n" + text[-half:]
