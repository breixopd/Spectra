from unittest.mock import AsyncMock, patch

import pytest

from spectra_api.services.system.setup import SystemSetupService


@pytest.fixture
def mock_setup_service():
    mock_session = AsyncMock()
    service = SystemSetupService(mock_session)
    # The actual code uses self.session, tests used service.db_session
    # Let's align
    service.db_session = mock_session
    return service


@pytest.mark.asyncio
async def test_check_database_connection_success(mock_setup_service):
    """Test successful database connection check."""
    # Mock execute to return valid result
    mock_setup_service.session.execute.return_value.scalar.return_value = 1

    # Check directly
    result = await mock_setup_service.check_database()
    assert result is True


@pytest.mark.asyncio
async def test_check_docker_connection_success(mock_setup_service):
    """Test successful Docker connection check."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"Docker version 20.10.0", b"")
        process_mock.returncode = 0
        mock_exec.return_value = process_mock

        result = await mock_setup_service.check_docker()
        assert result is True


@pytest.mark.asyncio
async def test_verify_system_requirements_all_pass(mock_setup_service):
    """Test full system verification where all checks pass."""
    with (
        patch.object(mock_setup_service, "check_database", new_callable=AsyncMock) as mock_db,
        patch.object(mock_setup_service, "check_docker", new_callable=AsyncMock) as mock_docker,
        patch.object(mock_setup_service, "check_directories", new_callable=AsyncMock) as mock_dirs,
    ):
        mock_db.return_value = True
        mock_docker.return_value = True
        mock_dirs.return_value = True

        report = await mock_setup_service.verify_system()

        assert report["status"] == "healthy"
        assert report["database"] is True
        assert report["docker"] is True


@pytest.mark.asyncio
async def test_verify_system_requirements_failure(mock_setup_service):
    """Test verification reporting failure."""
    with (
        patch.object(mock_setup_service, "check_database", new_callable=AsyncMock) as mock_db,
        patch.object(mock_setup_service, "check_docker", new_callable=AsyncMock) as m_d,
        patch.object(mock_setup_service, "check_directories", new_callable=AsyncMock) as m_dir,
    ):
        mock_db.return_value = False  # Fail DB
        m_d.return_value = True
        m_dir.return_value = True

        report = await mock_setup_service.verify_system()

        assert report["status"] == "unhealthy"
        assert report["database"] is False
