"""Sanitize user inputs before inclusion in LLM prompts."""

import logging
import re
import unicodedata

logger = logging.getLogger("spectra.ai.sanitizer")

# Patterns that could manipulate the LLM's behavior
INJECTION_PATTERNS = [
    re.compile(
        r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?|context)",
        re.IGNORECASE,
    ),
    re.compile(r"you\s+are\s+now\s+(?:a|an|in)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|(?:im_start|im_end|system|user|assistant)\|>", re.IGNORECASE),
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", re.IGNORECASE),
]


def sanitize_for_prompt(text: str, max_length: int = 10000, field_name: str = "input") -> str:
    """Sanitize user-provided text before inclusion in an LLM prompt.

    - Truncates to max_length
    - Strips known prompt injection patterns
    - Escapes delimiter-like sequences
    """
    if not isinstance(text, str):
        return str(text)[:max_length]

    # Normalize Unicode to prevent homoglyph bypasses (Cyrillic а vs Latin a, etc.)
    text = unicodedata.normalize("NFKD", text)
    # Strip zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)

    # Truncate
    if len(text) > max_length:
        logger.warning("Truncated %s from %d chars to %d", field_name, len(text), max_length)
        text = text[:max_length]

    # Strip injection patterns
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("Prompt injection pattern detected in %s", field_name)
            text = pattern.sub("[FILTERED]", text)

    return text
