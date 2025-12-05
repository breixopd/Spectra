import re

# Maximum output size to capture from subprocesses (1MB)
MAX_OUTPUT_SIZE: int = 1024 * 1024

# Maximum regex pattern length to prevent ReDoS attacks
MAX_REGEX_LENGTH: int = 500

# --- Dangerous Command Patterns (pre-compiled for performance) ---

_DANGEROUS_PATTERN_STRINGS: tuple[str, ...] = (
    r"rm\s+-rf\s+/$",  # rm -rf / (exactly root)
    r"rm\s+-rf\s+/\*",  # rm -rf /*
    r"rm\s+-rf\s+\*\s*$",  # rm -rf *
    r"mkfs\.",  # mkfs.ext4, etc.
    r"dd\s+if=.*of=/dev/",  # dd to device
    r">\s*/dev/sd",  # write to disk
    r"chmod\s+777\s+/$",  # chmod 777 / (exactly root)
    r"wget\s+.*\|\s*bash",  # wget | bash
    r"curl\s+.*\|\s*bash",  # curl | bash
    r":\(\)\{\s*:\|:\s*&\s*\};:",  # fork bomb
    r">\s*/etc/passwd",  # overwrite passwd
    r">\s*/etc/shadow",  # overwrite shadow
    r"/dev/null\s*>\s*/",  # null redirect to root
)

# Pre-compiled patterns for O(1) matching per pattern
DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERN_STRINGS
)
