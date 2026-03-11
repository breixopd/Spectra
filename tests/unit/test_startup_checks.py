"""
Tests for startup checks in app.core.lifespan.run_startup_checks().

Verifies DB connectivity, table existence, and disk space checks
using mocked database sessions and filesystem calls.
"""

from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_DiskUsage = namedtuple("usage", ["total", "used", "free"])


@pytest.mark.asyncio
async def test_db_connectivity_success(caplog):
    """Successful DB connectivity check logs OK."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    MagicMock(return_value=mock_session_ctx)  # session maker factory

    # Also mock the table check session
    mock_table_result = MagicMock()
    mock_table_result.fetchall.return_value = [
        ("users",), ("missions",), ("targets",), ("findings",), ("exploits",),
    ]
    mock_session2 = AsyncMock()
    mock_session2.execute = AsyncMock(return_value=mock_table_result)

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        ctx = AsyncMock()
        if call_count <= 1:
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
        else:
            ctx.__aenter__ = AsyncMock(return_value=mock_session2)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    with patch("app.core.lifespan.async_session_maker", side_effect=session_factory):
        with caplog.at_level("INFO", logger="spectra.core.lifespan"):
            from app.core.lifespan import run_startup_checks
            await run_startup_checks()

    assert any("Database connectivity verified" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_db_connectivity_failure(caplog):
    """DB connectivity failure logs a warning but doesn't raise."""
    mock_maker = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_maker.return_value = ctx

    with patch("app.core.lifespan.async_session_maker", side_effect=ConnectionError("refused")):
        with caplog.at_level("WARNING", logger="spectra.core.lifespan"):
            from app.core.lifespan import run_startup_checks
            await run_startup_checks()

    assert any("connectivity check failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_missing_tables_warning(caplog):
    """Missing tables produce a warning with table names."""
    # DB connectivity check - succeeds
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session1 = AsyncMock()
    mock_session1.execute = AsyncMock(return_value=mock_result)

    # Table check - only some tables exist
    mock_table_result = MagicMock()
    mock_table_result.fetchall.return_value = [("users",), ("missions",)]
    mock_session2 = AsyncMock()
    mock_session2.execute = AsyncMock(return_value=mock_table_result)

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        ctx = AsyncMock()
        if call_count <= 1:
            ctx.__aenter__ = AsyncMock(return_value=mock_session1)
        else:
            ctx.__aenter__ = AsyncMock(return_value=mock_session2)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    with patch("app.core.lifespan.async_session_maker", side_effect=session_factory):
        with caplog.at_level("WARNING", logger="spectra.core.lifespan"):
            from app.core.lifespan import run_startup_checks
            await run_startup_checks()

    assert any("Missing database tables" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_disk_space_ok(caplog):
    """Sufficient disk space logs OK."""
    # Mock away DB checks to avoid side effects
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_table_result = MagicMock()
    mock_table_result.fetchall.return_value = [
        ("users",), ("missions",), ("targets",), ("findings",), ("exploits",),
    ]

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        ctx = AsyncMock()
        if call_count <= 1:
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.execute = AsyncMock(return_value=mock_result)
        else:
            s2 = AsyncMock()
            s2.execute = AsyncMock(return_value=mock_table_result)
            ctx.__aenter__ = AsyncMock(return_value=s2)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    fake_usage = _DiskUsage(total=10_000_000_000, used=5_000_000_000, free=5_000_000_000)

    with patch("app.core.lifespan.async_session_maker", side_effect=session_factory):
        with patch("shutil.disk_usage", return_value=fake_usage):
            with caplog.at_level("INFO", logger="spectra.core.lifespan"):
                from app.core.lifespan import run_startup_checks
                await run_startup_checks()

    assert any("Disk space" in r.message and "free" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_low_disk_space_warning(caplog):
    """Less than 100MB free triggers a warning."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_table_result = MagicMock()
    mock_table_result.fetchall.return_value = [
        ("users",), ("missions",), ("targets",), ("findings",), ("exploits",),
    ]

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        ctx = AsyncMock()
        if call_count <= 1:
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
        else:
            s2 = AsyncMock()
            s2.execute = AsyncMock(return_value=mock_table_result)
            ctx.__aenter__ = AsyncMock(return_value=s2)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    # 50 MB free (below threshold)
    fake_usage = _DiskUsage(total=10_000_000_000, used=9_947_000_000, free=53_000_000)

    with patch("app.core.lifespan.async_session_maker", side_effect=session_factory):
        with patch("shutil.disk_usage", return_value=fake_usage):
            with caplog.at_level("WARNING", logger="spectra.core.lifespan"):
                from app.core.lifespan import run_startup_checks
                await run_startup_checks()

    assert any("Low disk space" in r.message for r in caplog.records)
