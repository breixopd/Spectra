"""Runtime host_ops_cli smoke tests."""

from unittest.mock import patch

import pytest

from spectra_scaling.runtime import host_ops_cli


@pytest.mark.asyncio
async def test_run_docker_prune_no_socket_skips():
    with patch("spectra_scaling.runtime.host_ops_cli.Path") as mpath:
        mpath.return_value.exists.return_value = False
        code = await host_ops_cli.run_docker_prune_round()
        assert code == 0
