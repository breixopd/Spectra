"""Unit tests for account deletion feature."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from spectra_api.api.schemas.system import DeleteAccountRequest

# --- Schema validation ---


def test_delete_account_request_valid():
    req = DeleteAccountRequest(password="mypassword")
    assert req.password == "mypassword"


def test_delete_account_request_empty_password_rejected():
    with pytest.raises(ValidationError):
        DeleteAccountRequest(password="")


def test_delete_account_request_missing_password_rejected():
    with pytest.raises(ValidationError):
        DeleteAccountRequest()


# --- Endpoint tests ---


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = "aaaa-bbbb-cccc-dddd"
    user.username = "testuser"
    user.hashed_password = "$2b$12$fakehash"
    user.is_superuser = False
    user.is_active = True
    return user


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()  # sync method — avoid AsyncMock coroutine warning
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result
    return session


@pytest.mark.asyncio
async def test_delete_account_wrong_password(mock_user, mock_session):
    """Should return 400 when password is incorrect."""
    from fastapi import HTTPException

    from spectra_api.api.routers.auth.session import delete_account

    body = DeleteAccountRequest(password="wrongpass")
    request = MagicMock()
    request.client.host = "127.0.0.1"

    with patch("spectra_api.api.routers.auth.session.verify_password", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await delete_account(
                request=request,
                response=MagicMock(),
                body=body,
                user=mock_user,
                session=mock_session,
            )
        assert exc_info.value.status_code == 400
        assert "incorrect" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_delete_account_last_superuser_blocked(mock_user, mock_session):
    """Should return 400 when trying to delete the last superuser."""
    from fastapi import HTTPException

    from spectra_api.api.routers.auth.session import delete_account

    mock_user.is_superuser = True
    body = DeleteAccountRequest(password="correct")
    request = MagicMock()
    request.client.host = "127.0.0.1"

    # Mock count query returning 1 (last superuser)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    mock_session.execute.return_value = count_result

    with patch("spectra_api.api.routers.auth.session.verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await delete_account(
                request=request,
                response=MagicMock(),
                body=body,
                user=mock_user,
                session=mock_session,
            )
        assert exc_info.value.status_code == 400
        assert "last superuser" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_delete_account_success(mock_user, mock_session):
    """Should delete user and return success message."""
    from spectra_api.api.routers.auth.session import delete_account

    body = DeleteAccountRequest(password="correct")
    request = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("spectra_api.api.routers.auth.session.verify_password", return_value=True),
        patch("spectra_api.api.routers.auth.session.audit_log_event", new_callable=AsyncMock),
    ):
        result = await delete_account(
            request=request,
            response=MagicMock(),
            body=body,
            user=mock_user,
            session=mock_session,
        )

    assert "permanently deleted" in result["detail"].lower()
    mock_session.delete.assert_called_once_with(mock_user)
    assert mock_session.commit.await_count >= 1


@pytest.mark.asyncio
async def test_delete_account_superuser_with_others_succeeds(mock_user, mock_session):
    """Superuser deletion should succeed when other superusers exist."""
    from spectra_api.api.routers.auth.session import delete_account

    mock_user.is_superuser = True
    body = DeleteAccountRequest(password="correct")
    request = MagicMock()
    request.client.host = "127.0.0.1"

    # First call: count query returns 2 (another superuser exists)
    # Second call: advisory lock for audit hash chaining
    # Third call: get_latest_hash in audit log_event
    # Fourth call: UPDATE audit_logs
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    advisory_lock_result = MagicMock()
    hash_result = MagicMock()
    hash_result.scalar_one_or_none.return_value = None
    update_result = MagicMock()
    mock_session.execute.side_effect = [count_result, advisory_lock_result, hash_result, update_result]

    with patch("spectra_api.api.routers.auth.session.verify_password", return_value=True):
        result = await delete_account(
            request=request,
            response=MagicMock(),
            body=body,
            user=mock_user,
            session=mock_session,
        )

    assert "permanently deleted" in result["detail"].lower()
    mock_session.delete.assert_called_once_with(mock_user)
