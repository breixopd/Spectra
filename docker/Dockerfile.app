# =============================================================================
# Spectra App - Optimized Multi-Stage Dockerfile
# =============================================================================
# Target size: ~500MB (down from 9GB)
# Removed: Playwright, PyTorch, sentence-transformers, nmap, browser deps

# --- Stage 1: Build dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install only app dependencies (no ML/testing deps)
COPY requirements-app.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-app.txt

# --- Stage 2: Runtime ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# Minimal runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Non-root user
RUN useradd --create-home --shell /bin/bash spectra && \
    chown -R spectra:spectra /app
USER spectra

# Copy startup script
COPY --chown=spectra:spectra scripts/start.sh /app/scripts/start.sh
RUN chmod +x /app/scripts/start.sh

# Create directories
RUN mkdir -p /app/reports /app/logs

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1"]
