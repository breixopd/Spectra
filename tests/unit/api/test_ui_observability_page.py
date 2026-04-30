"""UI route tests for observability HTML page access."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectra_api.ui.pages import router


@patch("spectra_api.ui.pages._get_ui_db_user", new_callable=AsyncMock)
@patch("spectra_api.ui.pages.get_ui_user", new_callable=AsyncMock)
def test_observability_forbidden_uses_branded_template(mock_get_ui_user, mock_get_db_user):
    mock_get_ui_user.return_value = {"sub": "regular"}
    db_user = MagicMock()
    db_user.role = "user"
    db_user.is_superuser = False
    mock_get_db_user.return_value = db_user

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/observability")

    assert resp.status_code == 403
    text = resp.text
    assert "403" in text
    assert "Access Denied" in text


@patch("spectra_api.ui.pages._get_ui_db_user", new_callable=AsyncMock)
@patch("spectra_api.ui.pages.get_ui_user", new_callable=AsyncMock)
def test_observability_allowed_renders_page(mock_get_ui_user, mock_get_db_user):
    mock_get_ui_user.return_value = {"sub": "admin"}
    db_user = MagicMock()
    db_user.role = "admin"
    db_user.is_superuser = False
    mock_get_db_user.return_value = db_user

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/observability")

    assert resp.status_code == 200
    assert "observability" in resp.text.lower()
