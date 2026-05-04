"""Shared plugin registry constants and command safety patterns."""

import re

# Maximum output size to capture from subprocesses (1MB)
MAX_OUTPUT_SIZE: int = 1024 * 1024

# Maximum regex pattern length to prevent ReDoS attacks
MAX_REGEX_LENGTH: int = 500

_DANGEROUS_PATTERN_STRINGS: tuple[str, ...] = (
    r"rm\s+-rf\s+/$",
    r"rm\s+-rf\s+/\*",
    r"rm\s+-rf\s+\*\s*$",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r">\s*/dev/sd",
    r"chmod\s+777\s+/$",
    r"wget\s+.*\|\s*bash",
    r"curl\s+.*\|\s*bash",
    r":\(\)\{\s*:\|:\s*&\s*\};:",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
    r"/dev/null\s*>\s*/",
    r"\$\(",
    r"`[^`]+`",
    r"\|\s*(?:bash|sh|curl|wget|nc|python|perl|ruby)",
    r"/dev/tcp/",
    r"python\d?\s+-c",
    r"perl\s+-e",
    r"base64\s+(?:-d|--decode)\s*\|",
    r";\s*(?:rm|wget|curl|bash|sh|nc|python|perl|ruby|cat\s*/etc)",
    r"&&\s*(?:rm|wget|curl|bash|sh|nc|python|perl|ruby|cat\s*/etc)",
    r"\|\|\s*(?:rm|wget|curl|bash|sh|nc|python|perl|ruby|cat\s*/etc)",
    r"-oA\s+\S+",
    r"-oX\s+\S+",
    r"-oN\s+\S+",
    r"-oG\s+\S+",
    r"--output\s+",
    r"--output-dir\s+",
)

DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in _DANGEROUS_PATTERN_STRINGS
)
