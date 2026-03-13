# Private Docker Registry & PyPI Server

[← Wiki Home](home.md) | [Deployment](deployment-guide.md) | [Scaling](scaling.md)

---

Guide for running a self-hosted Docker registry and private PyPI server on your dev/staging infrastructure. Both services sit behind Caddy for automatic TLS and htpasswd authentication.

## 1. Docker Registry

### 1.1 Quick Start

```bash
# Create storage directories
sudo mkdir -p /opt/registry /opt/registry-auth

# Generate htpasswd file (requires apache2-utils / httpd-tools)
sudo apt-get install -y apache2-utils
htpasswd -Bc /opt/registry-auth/htpasswd spectra

# Self-hosted Docker Registry
docker run -d --name registry --restart always \
  -p 5000:5000 \
  -v /opt/registry:/var/lib/registry \
  -v /opt/registry-auth:/auth \
  -e REGISTRY_AUTH=htpasswd \
  -e REGISTRY_AUTH_HTPASSWD_REALM="Spectra Registry" \
  -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd \
  registry:2
```

### 1.2 Registry UI

```bash
# Joxit Registry UI — browse images and tags in a web browser
docker run -d --name registry-ui --restart always \
  -p 8080:80 \
  -e REGISTRY_TITLE="Spectra Registry" \
  -e REGISTRY_URL=https://registry.yourdomain.com \
  -e SINGLE_REGISTRY=true \
  -e DELETE_IMAGES=true \
  joxit/docker-registry-ui:latest
```

### 1.3 TLS with Caddy Reverse Proxy

Create a Caddyfile that terminates TLS for both the registry and the UI:

```caddyfile
# /opt/registry/Caddyfile
registry.yourdomain.com {
    basicauth / {
        # Use `caddy hash-password` to generate bcrypt hashes
        spectra $2a$14$...your-bcrypt-hash...
    }

    reverse_proxy registry:5000 {
        header_up X-Forwarded-Proto {scheme}
    }

    header {
        Docker-Distribution-Api-Version "registry/2.0"
    }
}

registry-ui.yourdomain.com {
    reverse_proxy registry-ui:80
}
```

### 1.4 Pushing Spectra Images

```bash
# Log in to the private registry
docker login registry.yourdomain.com -u spectra

# Tag local images
docker tag spectra-app registry.yourdomain.com/spectra/app:latest
docker tag spectra-app registry.yourdomain.com/spectra/app:$(git rev-parse --short HEAD)

docker tag spectra-tools registry.yourdomain.com/spectra/tools:latest
docker tag spectra-tools registry.yourdomain.com/spectra/tools:$(git rev-parse --short HEAD)

# Push
docker push registry.yourdomain.com/spectra/app:latest
docker push registry.yourdomain.com/spectra/app:$(git rev-parse --short HEAD)
docker push registry.yourdomain.com/spectra/tools:latest
docker push registry.yourdomain.com/spectra/tools:$(git rev-parse --short HEAD)
```

### 1.5 CI Integration (GitHub Actions)

Add to `.github/workflows/release.yml`:

```yaml
name: Build and Push Images

on:
  push:
    tags: ['v*']

jobs:
  build-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to private registry
        uses: docker/login-action@v3
        with:
          registry: registry.yourdomain.com
          username: ${{ secrets.REGISTRY_USER }}
          password: ${{ secrets.REGISTRY_PASSWORD }}

      - name: Build and push app image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.app
          push: true
          tags: |
            registry.yourdomain.com/spectra/app:${{ github.ref_name }}
            registry.yourdomain.com/spectra/app:latest

      - name: Build and push tools image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.tools
          push: true
          tags: |
            registry.yourdomain.com/spectra/tools:${{ github.ref_name }}
            registry.yourdomain.com/spectra/tools:latest
```

### 1.6 Docker Hub Mirror / Pull-Through Cache

A pull-through cache avoids Docker Hub rate limits by caching upstream images locally.

```bash
# Create a registry that mirrors Docker Hub
docker run -d --name registry-mirror --restart always \
  -p 5001:5000 \
  -v /opt/registry-mirror:/var/lib/registry \
  -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io \
  registry:2
```

Configure Docker daemon to use the mirror — add to `/etc/docker/daemon.json`:

```json
{
  "registry-mirrors": ["https://registry-mirror.yourdomain.com"]
}
```

Restart Docker:

```bash
sudo systemctl restart docker
```

---

## 2. Private PyPI Server

### 2.1 Quick Start

```bash
# Create storage
sudo mkdir -p /opt/pypi/packages /opt/pypi/auth

# Generate htpasswd file for PyPI auth
htpasswd -Bc /opt/pypi/auth/htpasswd spectra

# pypiserver — lightweight private PyPI
docker run -d --name pypi --restart always \
  -p 8081:8080 \
  -v /opt/pypi/packages:/data/packages \
  -v /opt/pypi/auth/htpasswd:/data/.htpasswd \
  pypiserver/pypiserver:latest \
  run -P /data/.htpasswd /data/packages
```

### 2.2 Configuring pip

Add to `~/.pip/pip.conf` (Linux/macOS) or `%APPDATA%\pip\pip.ini` (Windows):

```ini
[global]
extra-index-url = https://pypi.yourdomain.com/simple/
trusted-host = pypi.yourdomain.com
```

Or per-project in the repo root:

```bash
# pip.conf checked into the repo
cat > pip.conf <<'EOF'
[global]
extra-index-url = https://pypi.yourdomain.com/simple/
trusted-host = pypi.yourdomain.com
EOF
```

In Docker builds, pass the config at build time:

```dockerfile
COPY pip.conf /etc/pip.conf
RUN pip install --no-cache-dir -r requirements.txt
```

### 2.3 Creating Packages from Spectra Shared Libraries

When extracting shared code (see [Microservices Split](microservices-split.md) § Shared Libraries), package it as a distributable wheel:

```
libs/
  spectra-common/
    pyproject.toml
    spectra_common/
      __init__.py
      models/
      schemas/
      auth/
      config.py
      events.py
      gateway.py
```

Example `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "spectra-common"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "httpx>=0.25",
]
```

Build and upload:

```bash
cd libs/spectra-common
pip install build twine
python -m build

# Upload to private PyPI
twine upload \
  --repository-url https://pypi.yourdomain.com \
  -u spectra -p "$PYPI_PASSWORD" \
  dist/*
```

### 2.4 Using Private Packages in Services

```bash
# Install from private PyPI
pip install spectra-common --extra-index-url https://pypi.yourdomain.com/simple/
```

In `requirements.txt`:

```
--extra-index-url https://pypi.yourdomain.com/simple/
spectra-common>=0.1.0
```

---

## 3. Docker Compose for Both Services

Save as `docker/docker-compose.registry.yml` alongside the existing compose files:

```yaml
# docker/docker-compose.registry.yml
# Usage: docker compose -f docker/docker-compose.registry.yml up -d
#
# Runs a private Docker registry, registry UI, and PyPI server
# behind Caddy with automatic TLS.

services:
  # ── Caddy (TLS termination) ────────────────────────────────
  caddy-registry:
    image: caddy:2-alpine
    container_name: spectra-caddy-registry
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile.registry:/etc/caddy/Caddyfile:ro
      - caddy_registry_data:/data
      - caddy_registry_config:/config
    depends_on:
      - registry
      - registry-ui
      - pypi
    restart: always
    networks:
      - registry-network

  # ── Docker Registry ─────────────────────────────────────────
  registry:
    image: registry:2
    container_name: spectra-registry
    expose:
      - "5000"
    volumes:
      - registry_data:/var/lib/registry
      - ./registry-auth:/auth:ro
    environment:
      REGISTRY_AUTH: htpasswd
      REGISTRY_AUTH_HTPASSWD_REALM: "Spectra Registry"
      REGISTRY_AUTH_HTPASSWD_PATH: /auth/htpasswd
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
    restart: always
    networks:
      - registry-network

  # ── Registry UI ─────────────────────────────────────────────
  registry-ui:
    image: joxit/docker-registry-ui:latest
    container_name: spectra-registry-ui
    expose:
      - "80"
    environment:
      REGISTRY_TITLE: "Spectra Registry"
      REGISTRY_URL: https://registry.yourdomain.com
      SINGLE_REGISTRY: "true"
      DELETE_IMAGES: "true"
    restart: always
    networks:
      - registry-network

  # ── PyPI Server ─────────────────────────────────────────────
  pypi:
    image: pypiserver/pypiserver:latest
    container_name: spectra-pypi
    command: run -P /data/.htpasswd /data/packages
    expose:
      - "8080"
    volumes:
      - pypi_packages:/data/packages
      - ./pypi-auth/htpasswd:/data/.htpasswd:ro
    restart: always
    networks:
      - registry-network

volumes:
  caddy_registry_data:
  caddy_registry_config:
  registry_data:
  pypi_packages:

networks:
  registry-network:
    driver: bridge
```

### Caddyfile for the registry stack

Save as `docker/Caddyfile.registry`:

```caddyfile
# docker/Caddyfile.registry
# Replace yourdomain.com with your actual domain.

registry.yourdomain.com {
    reverse_proxy registry:5000 {
        header_up X-Forwarded-Proto {scheme}
    }
    header Docker-Distribution-Api-Version "registry/2.0"
}

registry-ui.yourdomain.com {
    reverse_proxy registry-ui:80
}

pypi.yourdomain.com {
    reverse_proxy pypi:8080
}
```

### Setup Steps

```bash
# 1. Create auth files
mkdir -p docker/registry-auth docker/pypi-auth
htpasswd -Bc docker/registry-auth/htpasswd spectra
htpasswd -Bc docker/pypi-auth/htpasswd spectra

# 2. Edit Caddyfile.registry — replace yourdomain.com with your domain

# 3. Start
docker compose -f docker/docker-compose.registry.yml up -d

# 4. Verify
curl -u spectra https://registry.yourdomain.com/v2/_catalog
curl https://pypi.yourdomain.com/simple/
```

---

## 4. Pulling Spectra Images from the Private Registry

Update `docker/docker-compose.prod.yml` image references:

```yaml
# Before
image: ghcr.io/breixopd14/spectra-app:${VERSION:-latest}

# After — using private registry
image: registry.yourdomain.com/spectra/app:${VERSION:-latest}
```

On each deployment host, log in once:

```bash
docker login registry.yourdomain.com -u spectra
```
