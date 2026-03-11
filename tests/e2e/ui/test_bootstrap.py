"""Tests for Playwright UI bootstrap helpers."""

import pytest

from tests.e2e.ui.conftest import normalize_app_base_url


def test_normalize_app_base_url_accepts_http_and_strips_trailing_slash():
    assert normalize_app_base_url("http://spectra-ui-app:5000/") == "http://spectra-ui-app:5000"


def test_normalize_app_base_url_rejects_non_http_schemes():
    with pytest.raises(ValueError, match="APP_BASE_URL must use http or https"):
        normalize_app_base_url("file:///tmp/spectra")
