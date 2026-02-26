"""Smart wordlist generation based on target context."""


def generate_tech_wordlist(technologies: list[str]) -> list[str]:
    """Generate technology-specific paths based on discovered tech stack."""
    TECH_PATHS = {
        "wordpress": ["/wp-admin/", "/wp-login.php", "/wp-content/", "/xmlrpc.php", "/wp-json/", "/wp-includes/"],
        "joomla": ["/administrator/", "/components/", "/modules/", "/plugins/", "/templates/"],
        "drupal": ["/admin/", "/node/", "/sites/default/", "/user/login", "/update.php"],
        "php": ["/info.php", "/phpinfo.php", "/phpmyadmin/", "/config.php", "/wp-config.php.bak"],
        "apache": ["/.htaccess", "/server-status", "/server-info", "/.env", "/web.config"],
        "nginx": ["/nginx_status", "/.env", "/server-status"],
        "node": ["/api/", "/graphql", "/swagger", "/api-docs", "/.env", "/package.json"],
        "express": ["/api/v1/", "/api/v2/", "/health", "/status", "/debug"],
        "django": ["/admin/", "/api/", "/static/", "/media/", "/.env", "/settings/"],
        "flask": ["/api/", "/swagger/", "/debug/", "/console/", "/.env"],
        "tomcat": ["/manager/html", "/host-manager/", "/status", "/examples/"],
        "iis": ["/aspnet_client/", "/web.config", "/_vti_bin/", "/trace.axd"],
        "mysql": ["/phpmyadmin/", "/adminer/", "/dbadmin/"],
        "redis": ["/redis/", "/.redis"],
    }

    paths = set()
    paths.update(["/robots.txt", "/sitemap.xml", "/.git/", "/.env", "/backup/", "/admin/", "/login/", "/api/", "/.well-known/"])

    for tech in technologies:
        tech_lower = tech.lower()
        for key, tech_paths in TECH_PATHS.items():
            if key in tech_lower:
                paths.update(tech_paths)

    return sorted(paths)


def generate_credential_list(service: str, product: str | None = None) -> dict[str, list[str]]:
    """Generate default credential pairs for a service. Small list only — no brute force."""
    SERVICE_CREDS = {
        "ssh": {"users": ["root", "admin", "ubuntu", "pi", "ec2-user"], "passwords": ["root", "toor", "admin", "password", "ubuntu", "raspberry", "changeme"]},
        "ftp": {"users": ["anonymous", "ftp", "admin", "root"], "passwords": ["", "anonymous", "ftp", "admin", "password"]},
        "mysql": {"users": ["root", "admin", "mysql", "webapp"], "passwords": ["", "root", "admin", "password", "mysql", "toor"]},
        "postgresql": {"users": ["postgres", "admin", "root"], "passwords": ["postgres", "admin", "password", "root"]},
        "http": {"users": ["admin", "root", "administrator", "user"], "passwords": ["admin", "password", "admin123", "root", "123456", "changeme"]},
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
