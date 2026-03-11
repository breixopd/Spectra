from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SystemSetupRequest, UserCreate
from app.models.config import SystemConfig
from app.models.user import User
from app.services.system.setup import SystemSetupService


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
        llm_provider="litellm",
        llm_model="gpt-4",
        llm_api_key="sk-test",
        use_custom_db=False,
    )


@pytest.mark.asyncio
@patch("app.services.system.setup.get_password_hash")
@patch("app.services.system.setup.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
@patch("app.services.system.setup.SystemSetupService._generate_signing_keys")
@patch("app.services.system.setup.SystemSetupService._save_infra_config")
async def test_perform_setup_success(
    mock_save_infra,
    mock_gen_keys,
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
    mock_gen_keys.assert_called_once()
    mock_save_infra.assert_not_called()  # No infra changes


@pytest.mark.asyncio
async def test_create_admin_user(service, setup_request, mock_session):
    with patch("app.services.system.setup.get_password_hash") as mock_hash:
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
async def test_configure_system_persists_db_backed_profiles_and_fallbacks(
    service, mock_session
):
    setup_request = SystemSetupRequest(
        user=UserCreate(
            username="admin",
            email="admin@example.com",
            password="SecurePassword123!",
        ),
        provider_profiles={
            "default": {
                "provider": "litellm",
                "model": "gpt-4o-mini",
                "base_url": "https://example.test/v1",
                "api_key": "sk-primary",
            },
            "tier1": {
                "provider": "ollama",
                "model": "qwen2.5:3b",
                "base_url": "http://ollama:11434",
            },
            "fallback_1": {
                "provider": "litellm",
                "model": "gpt-4.1-mini",
                "base_url": "https://backup.test/v1",
                "api_key": "sk-backup",
            },
        },
        provider_routing={
            "default": "default",
            "tier1": "tier1",
        },
        provider_fallbacks={
            "default": ["fallback_1"],
        },
        embedding_model="all-MiniLM-L6-v2",
    )

    await service._configure_system(setup_request)

    added_configs = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], SystemConfig)
    ]
    config_map = {config.key: config for config in added_configs}

    assert "AI_PROVIDER_PROFILES" in config_map
    assert "AI_PROVIDER_ROUTING" in config_map
    assert "AI_PROVIDER_FALLBACKS" in config_map
    assert '"tier1": "tier1"' in config_map["AI_PROVIDER_ROUTING"].value
    assert '"fallback_1"' in config_map["AI_PROVIDER_FALLBACKS"].value


def test_system_setup_request_normalizes_legacy_api_provider_to_litellm():
    request = SystemSetupRequest(
        user=UserCreate(
            username="admin",
            email="admin@example.com",
            password="SecurePassword123!",
        ),
        llm_provider="api",
        llm_model="gpt-4o-mini",
        llm_api_key="sk-test",
    )

    assert request.llm_provider == "litellm"


@pytest.mark.asyncio
@patch("app.services.system.setup.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("app.services.system.setup.Path.exists")
async def test_save_infra_config(mock_exists, mock_file, mock_json_dump, service):
    mock_exists.return_value = False

    service._save_infra_config({"TEST_KEY": "TEST_VAL"})

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
        patch("app.services.system.setup.Path.mkdir"),
        patch("app.services.system.setup.Path.exists") as mock_exists,
    ):
        mock_exists.return_value = True
        result = await service.check_directories()
        assert result is True


@pytest.mark.asyncio
async def test_generate_signing_keys_exists(service):
    with patch("app.services.system.setup.Path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("app.services.system.setup.logger") as mock_logger:
            await service._generate_signing_keys()
            mock_logger.info.assert_any_call("Signing keys already exist")


@pytest.mark.asyncio
async def test_generate_signing_keys_new(service):
    with (
        patch("app.services.system.setup.Path.exists") as mock_exists,
        patch("app.services.system.setup.Path.mkdir"),
        patch("builtins.open", new_callable=mock_open),
        patch(
            "cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate"
        ) as mock_gen,
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
    ):
        mock_exists.return_value = False
        mock_key = MagicMock()
        mock_gen.return_value = mock_key

        await service._generate_signing_keys()

        mock_gen.assert_called_once()
        assert mock_to_thread.call_count == 2  # Two write_bytes calls
