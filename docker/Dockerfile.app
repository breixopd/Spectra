# Spectra App — FastAPI Backend
# Multi-stage build for minimal image size.

# --- Build Stage ---
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements/app.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r app.txt

# --- Runtime Stage ---
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Spectra App" \
      org.opencontainers.image.description="AI-Driven Security Assessment Platform" \
      org.opencontainers.image.source="https://github.com/breixopd14/spectra" \
      org.opencontainers.image.vendor="breixopd14"

ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.version="${BUILD_VERSION}"

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libpq5 \
    libcairo2 \
    curl \
    netcat-openbsd \
    ca-certificates \
    gnupg \
    gosu \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install Grype for container image scanning (pinned version)
RUN curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin v0.84.0 2>/dev/null || true

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --shell /bin/bash spectra && \
    groupadd -f docker && usermod -aG docker spectra && \
    mkdir -p /app/data /app/data/backups /app/logs && \
    chown -R spectra:spectra /app
# NOTE: We do NOT set USER here — start.sh runs as root to fix Docker socket GID,
# then drops to spectra via gosu before launching the app.

# Copy application code
COPY --chown=spectra:spectra scripts/ ./scripts/
COPY --chown=spectra:spectra app/ ./app/
COPY --chown=spectra:spectra alembic/ ./alembic/
COPY --chown=spectra:spectra config/alembic.ini ./config/alembic.ini
COPY --chown=spectra:spectra plugins/ ./plugins/
COPY --chown=spectra:spectra keys/ ./keys/
COPY --chown=spectra:spectra config/tailwind.config.js ./config/tailwind.config.js
RUN chmod +x /app/scripts/start.sh

# Build Tailwind CSS (pin v3 standalone binary; the current stylesheet pipeline is Tailwind v3-based)
ARG TAILWIND_VERSION=3.4.17
RUN curl -fsSLo tailwindcss-linux-x64 https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64 && \
    chmod +x tailwindcss-linux-x64 && \
    ./tailwindcss-linux-x64 -i app/static/css/input.css -o app/static/css/output.css --minify -c config/tailwind.config.js && \
    rm tailwindcss-linux-x64

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
