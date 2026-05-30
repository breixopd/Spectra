"""Tests for same-origin SPA serving (spectra_api.ui.spa)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id='root'>SPA-ROOT</div>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log('spa')", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path


def test_spa_serves_index_assets_and_excludes_api(tmp_path, monkeypatch):
    from spectra_api.ui import spa

    dist = _make_dist(tmp_path)
    monkeypatch.setattr(spa, "spa_dist_directory", lambda: dist)

    app = FastAPI()
    spa.register_spa(app)
    client = TestClient(app)

    # Deep client-side route falls back to the SPA shell.
    r = client.get("/missions/123")
    assert r.status_code == 200
    assert "SPA-ROOT" in r.text

    # Root falls back to the shell too.
    assert "SPA-ROOT" in client.get("/").text

    # Built asset is served from the mount.
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text

    # Favicon route serves the file.
    assert client.get("/favicon.svg").status_code == 200

    # The SPA owns login now (not the retired Jinja page).
    assert "SPA-ROOT" in client.get("/login").text

    # API and the server-rendered marketing/SEO surface are never swallowed by the SPA.
    assert client.get("/api/v1/anything").status_code == 404
    assert client.get("/legal/privacy").status_code == 404
    assert client.get("/pricing").status_code == 404


def test_register_spa_is_noop_without_build(monkeypatch):
    from spectra_api.ui import spa

    monkeypatch.setattr(spa, "spa_dist_directory", lambda: None)
    app = FastAPI()
    spa.register_spa(app)
    # No catch-all route registered, so an unknown path is a plain 404.
    assert TestClient(app).get("/missions").status_code == 404
