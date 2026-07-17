"""Runtime host_ops_cli smoke tests."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from spectra_scaling.runtime import host_ops_cli


@pytest.mark.asyncio
async def test_run_docker_prune_no_socket_skips():
    with patch("spectra_scaling.runtime.host_ops_cli.Path") as mpath:
        mpath.return_value.exists.return_value = False
        code = await host_ops_cli.run_docker_prune_round()
        assert code == 0


@pytest.mark.asyncio
async def test_run_docker_prune_keeps_volumes_without_explicit_opt_in(monkeypatch):
    prune_containers = AsyncMock()
    prune_images = AsyncMock()
    prune_volumes = AsyncMock()

    with patch("spectra_scaling.runtime.host_ops_cli.Path") as mpath:
        mpath.return_value.exists.return_value = True
        monkeypatch.setitem(
            sys.modules,
            "spectra_scaling.docker_client",
            SimpleNamespace(
                prune_containers=prune_containers,
                prune_images=prune_images,
                prune_volumes=prune_volumes,
            ),
        )
        code = await host_ops_cli.run_docker_prune_round()

    assert code == 0
    prune_images.assert_awaited_once_with(filters={"dangling": ["true"], "until": ["168h"]})
    prune_volumes.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_docker_prune_prunes_only_managed_volumes_when_requested(monkeypatch):
    prune_volumes = AsyncMock()

    with patch("spectra_scaling.runtime.host_ops_cli.Path") as mpath:
        mpath.return_value.exists.return_value = True
        monkeypatch.setitem(
            sys.modules,
            "spectra_scaling.docker_client",
            SimpleNamespace(
                prune_containers=AsyncMock(),
                prune_images=AsyncMock(),
                prune_volumes=prune_volumes,
            ),
        )
        code = await host_ops_cli.run_docker_prune_round(include_managed_volumes=True)

    assert code == 0
    prune_volumes.assert_awaited_once_with(filters={"label": ["spectra.managed=true"]})
