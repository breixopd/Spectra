"""Smart wordlist generation based on target context."""

import logging

logger = logging.getLogger(__name__)


def generate_credential_list(service: str, product: str | None = None) -> dict[str, list[str]]:
    """Generate default credential pairs for a service. Small list only — no brute force."""
    SERVICE_CREDS = {
        "ssh": {
            "users": ["root", "admin", "ubuntu", "pi", "ec2-user"],
            "passwords": ["root", "toor", "admin", "password", "ubuntu", "raspberry", "changeme"],
        },
        "ftp": {
            "users": ["anonymous", "ftp", "admin", "root"],
            "passwords": ["", "anonymous", "ftp", "admin", "password"],
        },
        "mysql": {
            "users": ["root", "admin", "mysql", "webapp"],
            "passwords": ["", "root", "admin", "password", "mysql", "toor"],
        },
        "postgresql": {"users": ["postgres", "admin", "root"], "passwords": ["postgres", "admin", "password", "root"]},
        "http": {
            "users": ["admin", "root", "administrator", "user"],
            "passwords": ["admin", "password", "admin123", "root", "123456", "changeme"],
        },
        "smb": {"users": ["administrator", "admin", "guest"], "passwords": ["", "admin", "password", "Password1"]},
        "rdp": {"users": ["administrator", "admin"], "passwords": ["admin", "password", "Password1", "P@ssw0rd"]},
        "telnet": {"users": ["root", "admin"], "passwords": ["root", "admin", "password", "default"]},
        "redis": {"users": [""], "passwords": ["", "redis", "password", "foobared"]},
        "mongodb": {"users": ["admin", "root"], "passwords": ["admin", "password", "root", "changeme"]},
    }

    creds = SERVICE_CREDS.get(service.lower(), SERVICE_CREDS["http"])

    if product:
        product_lower = product.lower()
        PRODUCT_CREDS = {
            "tomcat": {"users": ["tomcat", "admin", "manager"], "passwords": ["tomcat", "s3cret", "admin", "manager"]},
            "jenkins": {"users": ["admin"], "passwords": ["admin", "jenkins", "password"]},
            "wordpress": {"users": ["admin", "wp-admin"], "passwords": ["admin", "password", "wordpress"]},
        }
        for key, pcreds in PRODUCT_CREDS.items():
            if key in product_lower:
                creds["users"] = list(set(creds["users"] + pcreds["users"]))
                creds["passwords"] = list(set(creds["passwords"] + pcreds["passwords"]))

    return creds
