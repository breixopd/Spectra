from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from spectra_scaling.docker_client import (
    _failed_tasks_from_swarm,
    _get_registry_digest_v2,
    _parse_swarm_timestamp,
)


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
    assert _FakeAsyncClient.requested_urls == ["https://registry.example.com/v2/team/image/manifests/stable"]
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


# --- Swarm timestamp parsing ---


def test_parse_swarm_timestamp_handles_nanoseconds_and_z():
    # Docker emits 9 fractional digits + trailing Z, which datetime.fromisoformat rejects.
    parsed = _parse_swarm_timestamp("2026-05-30T03:21:09.123456789Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.microsecond == 123456


def test_parse_swarm_timestamp_rejects_garbage():
    assert _parse_swarm_timestamp("") is None
    assert _parse_swarm_timestamp("not-a-timestamp") is None


# --- Active failure detection (smart-heal trigger) ---


class _FakeSwarmService:
    """Minimal stand-in for a docker-py Service: only ``name`` and ``tasks()``."""

    def __init__(self, tasks: list[dict]):
        self.name = "fake_svc"
        self._tasks = tasks

    def tasks(self, filters=None):
        return self._tasks


def _task(state: str, desired: str, *, ago_secs: float = 0.0, tid: str = "t") -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=ago_secs)).isoformat().replace("+00:00", "Z")
    return {"ID": tid, "DesiredState": desired, "Status": {"State": state, "Timestamp": ts}}


def test_failed_tasks_counts_desired_running_but_failed():
    # Swarm still wants it up but it's failed right now -> active failure.
    svc = _FakeSwarmService([_task("failed", "running", tid="a")])
    assert _failed_tasks_from_swarm(svc) == 1


def test_failed_tasks_ignores_old_superseded_failures():
    # A failure from long ago that swarm already replaced (desired=shutdown) must NOT count,
    # otherwise a healthy N/N service force-restarts forever.
    svc = _FakeSwarmService(
        [
            _task("failed", "shutdown", ago_secs=3600, tid="old"),
            _task("running", "running", tid="cur"),
        ]
    )
    assert _failed_tasks_from_swarm(svc) == 0


def test_failed_tasks_counts_recent_crashloop_failure():
    # Failed very recently, even though swarm already moved on -> crash-loop signal.
    svc = _FakeSwarmService([_task("failed", "shutdown", ago_secs=5, tid="recent")])
    assert _failed_tasks_from_swarm(svc) == 1


def test_failed_tasks_dedupes_by_id_and_ignores_healthy():
    svc = _FakeSwarmService(
        [
            _task("running", "running", tid="r1"),
            _task("running", "running", tid="r2"),
            _task("complete", "shutdown", ago_secs=10, tid="done"),
        ]
    )
    assert _failed_tasks_from_swarm(svc) == 0
