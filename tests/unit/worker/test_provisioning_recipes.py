from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_recipes_module():
    module_path = Path(__file__).resolve().parents[3] / "app/services/provisioning/recipes.py"
    spec = spec_from_file_location("test_provisioning_recipes_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docker_install_recipe_uses_official_apt_repository():
    recipes = _load_recipes_module()
    command = recipes._DOCKER_INSTALL_STEPS[0].command

    assert "command -v docker" in command
    assert "curl -fsSL https://get.docker.com | sh" not in command
    assert "apt-get install -y ca-certificates curl gnupg" in command
    assert "/etc/apt/keyrings/docker.asc" in command
    assert "/etc/apt/sources.list.d/docker.list" in command
    assert "https://download.docker.com/linux/${ID}" in command
    assert "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" in command


def test_sandbox_worker_recipe_uses_versioned_tools_image_with_local_tag_fallback():
    recipes = _load_recipes_module()
    command = recipes.PROVISIONING_RECIPES["sandbox_worker"][len(recipes._DOCKER_INSTALL_STEPS)].command

    assert "docker pull {registry}/spectra-tools:{version}" in command
    assert "docker tag {registry}/spectra-tools:{version} spectra-tools:latest" in command
    assert "docker build -t spectra-tools /tmp/spectra-tools/" in command
    assert "docker pull ghcr.io/spectra/spectra-tools:latest" not in command


@pytest.mark.asyncio
async def test_server_deployer_installs_docker_from_official_apt_repository():
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()

    with patch.object(deployer, "_run_ssh", new_callable=AsyncMock, return_value=0) as mock_run:
        result = await deployer._install_docker(["ssh"], [])

    assert result == 0
    command = mock_run.await_args.args[1]
    assert "curl -fsSL https://get.docker.com | sh" not in command
    assert "/etc/apt/keyrings/docker.gpg" in command
    assert "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" in command
    assert "docker compose version >/dev/null 2>&1" in command


@pytest.mark.asyncio
async def test_server_deployer_fails_when_service_deploy_step_fails():
    from app.services.infrastructure.deploy import DeploymentStatus, ServerDeployer

    deployer = ServerDeployer()

    with (
        patch.object(deployer, "_ensure_known_host", return_value=Path("/tmp/deployer_known_hosts")),
        patch.object(deployer, "_run_ssh", new_callable=AsyncMock, return_value=0),
        patch.object(deployer, "_install_docker", new_callable=AsyncMock, return_value=0),
        patch.object(deployer, "_deploy_services", new_callable=AsyncMock, return_value=1) as mock_deploy,
        patch.object(deployer, "_verify_deployment", new_callable=AsyncMock) as mock_verify,
    ):
        result = await deployer.deploy_to_server(
            server_id="srv-1",
            hostname="example.com",
            ssh_user="ubuntu",
            harden=False,
            services=["app", "scheduler"],
        )

    assert result.status is DeploymentStatus.FAILED
    assert result.message == "Service deployment failed"
    mock_deploy.assert_awaited_once()
    mock_verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_deployer_passes_requested_services_to_verification():
    from app.services.infrastructure.deploy import DeploymentStatus, ServerDeployer

    deployer = ServerDeployer()
    requested_services = ["app", "scheduler"]

    with (
        patch.object(deployer, "_ensure_known_host", return_value=Path("/tmp/deployer_known_hosts")),
        patch.object(deployer, "_run_ssh", new_callable=AsyncMock, return_value=0),
        patch.object(deployer, "_install_docker", new_callable=AsyncMock, return_value=0),
        patch.object(deployer, "_deploy_services", new_callable=AsyncMock, return_value=0),
        patch.object(deployer, "_verify_deployment", new_callable=AsyncMock, return_value=True) as mock_verify,
    ):
        result = await deployer.deploy_to_server(
            server_id="srv-2",
            hostname="example.com",
            ssh_user="ubuntu",
            harden=False,
            services=requested_services,
        )

    assert result.status is DeploymentStatus.COMPLETE
    mock_verify.assert_awaited_once_with(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=/tmp/deployer_known_hosts",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            "-p",
            "22",
            "ubuntu@example.com",
        ],
        requested_services,
        result.logs,
    )


def test_server_deployer_builds_strict_known_hosts_ssh_base():
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()

    result = deployer._build_ssh_base(
        hostname="example.com",
        user="ubuntu",
        port=2222,
        key="/tmp/id_ed25519",
        known_hosts_path=Path("/tmp/deployer_known_hosts"),
    )

    assert result == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=/tmp/deployer_known_hosts",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "BatchMode=yes",
        "-p",
        "2222",
        "-i",
        "/tmp/id_ed25519",
        "ubuntu@example.com",
    ]


def test_server_deployer_uses_pinned_known_host_entry_without_duplicates(tmp_path):
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()
    known_hosts_path = tmp_path / "config" / "deployer_known_hosts"
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    known_hosts_path.write_text(
        "[example.com]:2222 ssh-ed25519 AAAAOLD\nother.example ssh-ed25519 AAAAOTHER\n",
        encoding="utf-8",
    )

    with (
        patch.object(deployer, "_known_hosts_path", return_value=known_hosts_path),
        patch("app.services.infrastructure.deploy.subprocess.run") as mock_run,
    ):
        result = deployer._ensure_known_host(
            hostname="example.com",
            port=2222,
            pinned_known_host="[example.com]:2222 ssh-ed25519 AAAANEW\n[example.com]:2222 ssh-ed25519 AAAANEW\n",
        )

    assert result == known_hosts_path
    assert known_hosts_path.read_text(encoding="utf-8") == (
        "other.example ssh-ed25519 AAAAOTHER\n"
        "[example.com]:2222 ssh-ed25519 AAAANEW\n"
    )
    mock_run.assert_not_called()


def test_server_deployer_keyscan_failure_raises_runtime_error(tmp_path):
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()
    known_hosts_path = tmp_path / "config" / "deployer_known_hosts"
    error = subprocess.CalledProcessError(
        1,
        ["ssh-keyscan", "-p", "22", "bad.example"],
        stderr="lookup bad.example: no address associated with name",
    )

    with (
        patch.object(deployer, "_known_hosts_path", return_value=known_hosts_path),
        patch("app.services.infrastructure.deploy.subprocess.run", side_effect=error),
    ):
        with pytest.raises(RuntimeError, match="ssh-keyscan failed for bad.example:22"):
            deployer._ensure_known_host(hostname="bad.example", port=22)


def test_server_deployer_keyscan_persists_scanned_host_keys(tmp_path):
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()
    known_hosts_path = tmp_path / "config" / "deployer_known_hosts"
    scan_result = MagicMock(stdout="# comment\n[example.com]:2222 ssh-ed25519 AAAASCAN\n")

    with (
        patch.object(deployer, "_known_hosts_path", return_value=known_hosts_path),
        patch("app.services.infrastructure.deploy.subprocess.run", return_value=scan_result) as mock_run,
    ):
        result = deployer._ensure_known_host(hostname="example.com", port=2222)

    assert result == known_hosts_path
    assert known_hosts_path.read_text(encoding="utf-8") == "[example.com]:2222 ssh-ed25519 AAAASCAN\n"
    expected_executable = deployer._ssh_keyscan_executable()
    mock_run.assert_called_once_with(
        [expected_executable, "-p", "2222", "example.com"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


@pytest.mark.asyncio
async def test_server_deployer_verify_deployment_checks_running_compose_services():
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()

    with patch.object(deployer, "_run_ssh", new_callable=AsyncMock, return_value=0) as mock_run:
        result = await deployer._verify_deployment(["ssh"], ["app", "ai-svc"], [])

    assert result is True
    command = mock_run.await_args.args[1]
    assert "docker compose ps --services --status running" in command
    assert "ERROR: Missing /opt/spectra/docker-compose.yml during verification." in command
    assert "ERROR: Requested services not running:${missing_services}" in command
    assert "for service in app ai-svc; do" in command


@pytest.mark.asyncio
async def test_server_deployer_deploy_services_fails_closed_without_compose_file():
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()

    with patch.object(deployer, "_run_ssh", new_callable=AsyncMock, return_value=1) as mock_run:
        result = await deployer._deploy_services(["ssh"], ["app", "scheduler"], [])

    assert result == 1
    command = mock_run.await_args.args[1]
    assert "ERROR: No docker-compose.yml found at /opt/spectra. Upload config first." in command
    assert "exit 1" in command