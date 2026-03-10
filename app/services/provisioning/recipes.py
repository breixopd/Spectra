"""Provisioning recipes for remote Spectra services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProvisionStep:
    """A single step in a provisioning recipe."""
    name: str
    command: str
    timeout: int = 120
    required: bool = True


# Docker installation (shared across all service types)
_DOCKER_INSTALL_STEPS = [
    ProvisionStep(
        name="Check/Install Docker",
        command=(
            "if command -v docker &>/dev/null; then echo 'Docker already installed'; "
            "else curl -fsSL https://get.docker.com | sh; fi"
        ),
        timeout=300,
    ),
    ProvisionStep(
        name="Start Docker daemon",
        command="systemctl enable docker && systemctl start docker && docker info >/dev/null 2>&1",
        timeout=30,
    ),
    ProvisionStep(
        name="Create Spectra network",
        command="docker network create spectra-remote 2>/dev/null || true",
        timeout=10,
        required=False,
    ),
]


PROVISIONING_RECIPES: dict[str, list[ProvisionStep]] = {
    "sandbox_worker": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Pull Spectra tools image",
            command="docker pull ghcr.io/spectra/spectra-tools:latest || docker build -t spectra-tools /tmp/spectra-tools/ || echo 'will_build_next'",
            timeout=600,
            required=False,
        ),
        ProvisionStep(
            name="Stop existing sandbox worker",
            command="docker stop spectra-sandbox-worker 2>/dev/null; docker rm spectra-sandbox-worker 2>/dev/null; echo ok",
            timeout=15,
            required=False,
        ),
        ProvisionStep(
            name="Start sandbox worker",
            command=(
                "docker run -d --name spectra-sandbox-worker "
                "--network spectra-remote --restart unless-stopped "
                "-p {service_port}:5000 "
                "{env_vars} "
                "-v /var/run/docker.sock:/var/run/docker.sock:ro "
                "spectra-tools"
            ),
            timeout=30,
        ),
    ],
}
