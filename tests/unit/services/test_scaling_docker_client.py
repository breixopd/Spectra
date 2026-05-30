from unittest.mock import patch

import httpx
import pytest

from spectra_scaling.docker_client import _get_registry_digest_v2


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class _FakeAsyncClient:
    init_kwargs: list[dict] = []
    requested_urls: list[str] = []
    outcomes: dict[str, _FakeResponse | Exception] = {}

    def __init__(self, *args, **kwargs):
        self.init_kwargs.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def head(self, url: str, headers: dict[str, str]):
        self.requested_urls.append(url)
        outcome = self.outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _reset_fake_client() -> None:
    _FakeAsyncClient.init_kwargs = []
    _FakeAsyncClient.requested_urls = []
    _FakeAsyncClient.outcomes = {}


@pytest.mark.asyncio
async def test_get_registry_digest_v2_prefers_verified_https():
    _reset_fake_client()
    _FakeAsyncClient.outcomes = {
        "https://registry.example.com/v2/team/image/manifests/stable": _FakeResponse(
            200,
            {"Docker-Content-Digest": "sha256:" + "a" * 64},
        ),
    }

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        digest = await _get_registry_digest_v2("registry.example.com/team/image:stable")

    assert digest == "a" * 64
    assert _FakeAsyncClient.requested_urls == [
        "https://registry.example.com/v2/team/image/manifests/stable"
    ]
    assert all("verify" not in kwargs for kwargs in _FakeAsyncClient.init_kwargs)


@pytest.mark.asyncio
async def test_get_registry_digest_v2_falls_back_to_http_for_insecure_registries():
    _reset_fake_client()
    _FakeAsyncClient.outcomes = {
        "https://registry.internal:5000/v2/team/image/manifests/latest": httpx.ConnectError("tls failed"),
        "http://registry.internal:5000/v2/team/image/manifests/latest": _FakeResponse(
            200,
            {"Docker-Content-Digest": "sha256:" + "b" * 64},
        ),
    }

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        digest = await _get_registry_digest_v2("registry.internal:5000/team/image")

    assert digest == "b" * 64
    assert _FakeAsyncClient.requested_urls == [
        "https://registry.internal:5000/v2/team/image/manifests/latest",
        "http://registry.internal:5000/v2/team/image/manifests/latest",
    ]
    assert all("verify" not in kwargs for kwargs in _FakeAsyncClient.init_kwargs)
