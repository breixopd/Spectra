from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.schemas.auth import UserCreate
from spectra_api.api.schemas.system import SystemSetupRequest
from spectra_api.services.system.setup import SystemSetupService
from spectra_platform.models.config import SystemConfig
from spectra_platform.models.user import User


@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result
    return session


@pytest.fixture
def service(mock_session):
    return SystemSetupService(mock_session)


@pytest.fixture
def setup_request():
    return SystemSetupRequest(
        user=UserCreate(
            username="admin",
            email="admin@example.com",
            password="SecurePassword123!",  # Meets complexity reqs
        ),
        tensorzero_gateway_url="http://tensorzero:3000",
        use_custom_db=False,
    )


@pytest.mark.asyncio
@patch("spectra_api.services.system.setup.get_password_hash")
@patch("spectra_api.services.system.setup.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
@patch("spectra_api.services.system.setup.SystemSetupService._save_infra_config")
async def test_perform_setup_success(
    mock_save_infra,
    mock_hydrate,
    mock_hash,
    service,
    setup_request,
    mock_session,
):
    mock_hash.return_value = "hashed_secret"

    user = await service.perform_setup(setup_request)

    assert isinstance(user, User)
    assert user.username == "admin"
    assert user.email == "admin@example.com"
    assert user.hashed_password == "hashed_secret"
    assert user.is_superuser

    mock_session.add.assert_called()  # Check user added
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(user)

    mock_hydrate.assert_awaited_once()
    mock_save_infra.assert_not_called()  # No infra changes


@pytest.mark.asyncio
async def test_create_admin_user(service, setup_request, mock_session):
    with patch("spectra_api.services.system.setup.get_password_hash") as mock_hash:
        mock_hash.return_value = "hashed"
        user = await service._create_admin_user(setup_request)

        assert user.username == "admin"
        mock_session.add.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_configure_system(service, setup_request, mock_session):
    await service._configure_system(setup_request)
    # Check session.add called for configs
    assert mock_session.add.call_count >= 2  # At least provider and model


@pytest.mark.asyncio
async def test_configure_system_persists_tensorzero_config(service, mock_session):
    setup_request = SystemSetupRequest(
        user=UserCreate(
            username="admin",
            email="admin@example.com",
            password="SecurePassword123!",
        ),
        tensorzero_gateway_url="http://tensorzero:3000",
        tensorzero_api_key="tz-key-test",
        embedding_model="all-MiniLM-L6-v2",
    )

    await service._configure_system(setup_request)

    added_configs = [call.args[0] for call in mock_session.add.call_args_list if isinstance(call.args[0], SystemConfig)]
    config_map = {config.key: config for config in added_configs}

    assert "TENSORZERO_GATEWAY_URL" in config_map
    assert config_map["TENSORZERO_GATEWAY_URL"].value == "http://tensorzero:3000"
    assert "EMBEDDING_MODEL" in config_map


@pytest.mark.asyncio
@patch("spectra_api.services.system.setup.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("spectra_api.services.system.setup.Path.mkdir")
@patch("spectra_api.services.system.setup.Path.exists")
async def test_save_infra_config(mock_exists, mock_mkdir, mock_file, mock_json_dump, service):
    mock_exists.return_value = False

    service._save_infra_config({"TEST_KEY": "TEST_VAL"})

    mock_mkdir.assert_called_once()
    mock_file.assert_called()
    mock_json_dump.assert_called()


@pytest.mark.asyncio
async def test_check_database_success(service, mock_session):
    mock_session.execute.return_value = True
    result = await service.check_database()
    assert result is True
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_check_directories(service):
    with (
        patch("spectra_api.services.system.setup.Path.mkdir"),
        patch("spectra_api.services.system.setup.Path.exists") as mock_exists,
    ):
        mock_exists.return_value = True
        result = await service.check_directories()
        assert result is True



