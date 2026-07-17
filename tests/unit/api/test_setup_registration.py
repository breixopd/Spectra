"""Security regressions for atomic first-run setup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request, Response


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/setup",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_setup_acquires_transaction_lock_before_checking_for_users() -> None:
    from spectra_api.api.routers.auth.registration import setup_admin_user

    session = AsyncMock()
    lock_result = MagicMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[lock_result, existing_result])

    setup_input = MagicMock()
    created_user = MagicMock()

    with patch(
        "spectra_api.services.system.setup.SystemSetupService.perform_setup",
        new=AsyncMock(return_value=created_user),
    ):
        result = await setup_admin_user.__wrapped__(
            _request(),
            Response(),
            setup_input,
            session,
        )

    assert result is created_user
    assert session.execute.await_count == 2
    first_statement = str(session.execute.await_args_list[0].args[0])
    assert "pg_advisory_xact_lock" in first_statement


@pytest.mark.asyncio
async def test_setup_rejects_second_admin_while_holding_transaction_lock() -> None:
    from spectra_api.api.routers.auth.registration import setup_admin_user

    session = AsyncMock()
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = "existing-user"
    session.execute = AsyncMock(side_effect=[MagicMock(), existing_result])

    with (
        patch("spectra_api.services.system.setup.SystemSetupService.perform_setup", new=AsyncMock()) as setup,
        pytest.raises(HTTPException) as exc,
    ):
        await setup_admin_user.__wrapped__(
            _request(),
            Response(),
            MagicMock(),
            session,
        )

    assert exc.value.status_code == 403
    setup.assert_not_awaited()
