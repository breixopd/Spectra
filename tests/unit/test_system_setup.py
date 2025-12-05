import pytest
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from app.services.system.setup import SystemSetupService
from app.api.schemas import SystemSetupRequest, UserCreate
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User

@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
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
            password="SecurePassword123!" # Meets complexity reqs
        ),
        llm_provider="api",
        llm_model="gpt-4",
        llm_api_key="sk-test",
        use_custom_db=False,
        use_custom_redis=False
    )

@pytest.mark.asyncio
@patch("app.services.system.setup.get_password_hash")
@patch("app.services.system.setup.close_global_llm_client", new_callable=AsyncMock)
@patch("app.services.system.setup.get_llm_client")
@patch("app.services.system.setup.SystemSetupService._generate_signing_keys")
@patch("app.services.system.setup.SystemSetupService._save_infra_config")
async def test_perform_setup_success(
    mock_save_infra,
    mock_gen_keys,
    mock_get_llm, 
    mock_close_llm,
    mock_hash,
    service, 
    setup_request,
    mock_session
):
    mock_hash.return_value = "hashed_secret"
    
    user = await service.perform_setup(setup_request)
    
    assert isinstance(user, User)
    assert user.username == "admin"
    assert user.email == "admin@example.com"
    assert user.hashed_password == "hashed_secret"
    assert user.is_superuser
    
    mock_session.add.assert_called() # Check user added
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(user)
    
    mock_gen_keys.assert_called_once()
    mock_close_llm.assert_called_once()
    mock_get_llm.assert_called_once()
    mock_save_infra.assert_not_called() # No infra changes

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
    assert mock_session.add.call_count >= 2 # At least provider and model

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
@patch("app.services.system.setup.settings")
async def test_check_redis_success(mock_settings, service):
    mock_settings.REDIS_HOST = "localhost"
    mock_settings.REDIS_PORT = 6379
    mock_settings.REDIS_PASSWORD = None
    
    with patch("redis.asyncio.Redis") as mock_redis_cls: 
        mock_redis = AsyncMock()
        mock_redis_cls.return_value = mock_redis
        
        result = await service.check_redis()
        
        assert result is True
        mock_redis.ping.assert_called_once()
        mock_redis.close.assert_called_once()

@pytest.mark.asyncio
async def test_check_database_success(service, mock_session):
    mock_session.execute.return_value = True
    result = await service.check_database()
    assert result is True
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_check_directories(service):
    with patch("app.services.system.setup.Path.mkdir") as mock_mkdir, \
         patch("app.services.system.setup.Path.exists") as mock_exists:
        mock_exists.return_value = True
        result = await service.check_directories()
        assert result is True

@pytest.mark.asyncio
async def test_generate_signing_keys_exists(service):
    with patch("app.services.system.setup.Path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("app.services.system.setup.logger") as mock_logger:
            service._generate_signing_keys()
            mock_logger.info.assert_any_call("Signing keys already exist")

@pytest.mark.asyncio
async def test_generate_signing_keys_new(service):
    with patch("app.services.system.setup.Path.exists") as mock_exists, \
         patch("app.services.system.setup.Path.mkdir") as mock_mkdir, \
         patch("builtins.open", new_callable=mock_open), \
         patch("cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate") as mock_gen:
        
        mock_exists.return_value = False
        mock_key = MagicMock()
        mock_gen.return_value = mock_key
        
        service._generate_signing_keys()
        
        mock_gen.assert_called_once()
        mock_key.private_bytes.assert_called_once()
        mock_key.public_key.return_value.public_bytes.assert_called_once()
