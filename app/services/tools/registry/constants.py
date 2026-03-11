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
    r"\$\(",  # $() command substitution
    r"`[^`]+`",  # backtick command substitution
    r"\|\s*(?:bash|sh|curl|wget|nc|python|perl|ruby)",  # pipe to interpreter/downloader
    r"/dev/tcp/",  # bash /dev/tcp redirection
    r"python\d?\s+-c",  # python -c execution
    r"perl\s+-e",  # perl -e execution
    r"base64\s+(?:-d|--decode)\s*\|",  # base64 decode pipe
)

# Pre-compiled patterns for O(1) matching per pattern
DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERN_STRINGS
)
