"""Safety tests for the embedded maintenance daemon."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from spectra_scaling.runtime import embedded_daemon


@pytest.mark.asyncio
async def test_embedded_prune_is_scoped_to_managed_resources(monkeypatch):
    prune_containers = AsyncMock()
    prune_images = AsyncMock()

    with patch("spectra_scaling.runtime.embedded_daemon.Path") as path_cls:
        path_cls.return_value.exists.return_value = True
        # The daemon deliberately prunes on a six-hour cadence. Keep this
        # assertion independent of the runner's host uptime by placing the
        # first loop iteration beyond that interval.
        loop = SimpleNamespace(time=lambda: 21_601.0)
        monkeypatch.setitem(
            sys.modules,
            "spectra_scaling.docker_client",
            SimpleNamespace(
                prune_containers=prune_containers,
                prune_images=prune_images,
            ),
        )
        monkeypatch.setattr(embedded_daemon.asyncio, "get_running_loop", lambda: loop)
        monkeypatch.setattr(
            embedded_daemon.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError]),
        )

        with pytest.raises(asyncio.CancelledError):
            await embedded_daemon.embedded_ops_loop("worker", interval_secs=1)

    prune_containers.assert_awaited_once_with(filters={"label": ["spectra.managed=true"], "until": ["72h"]})
    prune_images.assert_awaited_once_with(
        filters={"label": ["spectra.managed=true"], "dangling": ["true"], "until": ["240h"]}
    )
