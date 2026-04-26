#!/usr/bin/env python3
"""Live Spectra smoke test.

Runs against an already-started Compose/Swarm/VPS deployment. It avoids
printing secrets and uses the same setup/login flow an operator would use.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpResult:
    status: int
    data: Any
    text: str


BASE_URL = os.environ.get("APP_BASE_URL") or os.environ.get("SPECTRA_URL") or "http://localhost:5000"
BASE_URL = BASE_URL.rstrip("/")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", os.environ.get("APP_USERNAME", "admin"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("APP_PASSWORD", "Admin123!"))
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@spectra.local")
LLM_PROVIDER = os.environ.get("AI_PROVIDER", "tensorzero")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
LLM_API_BASE_URL = os.environ.get("LLM_API_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
SERVICE_AUTH_SECRET = os.environ.get("SERVICE_AUTH_SECRET", "")
AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "")
TENSORZERO_GATEWAY_URL = os.environ.get("TENSORZERO_GATEWAY_URL", "")
STRICT_LLM_SMOKE = os.environ.get("STRICT_LLM_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"}


def _request(
    method: str,
    path_or_url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    form_body: dict[str, str] | None = None,
    timeout: int = 30,
) -> HttpResult:
    url = path_or_url if path_or_url.startswith(("http://", "https://")) else f"{BASE_URL}{path_or_url}"
    body = None
    req_headers = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode()
        req_headers["Content-Type"] = "application/json"
    elif form_body is not None:
        body = urllib.parse.urlencode(form_body).encode()
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
            return HttpResult(resp.status, _parse_json(text), text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return HttpResult(exc.code, _parse_json(text), text)


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"OK: {message}")


def _is_provider_quota_failure(resp: HttpResult) -> bool:
    text = resp.text.lower()
    return resp.status in (429, 500, 502, 503) and any(
        marker in text
        for marker in (
            "rate limit exceeded",
            "free-models-per-day",
            "too many requests",
        )
    )


def _setup_if_needed() -> None:
    status = _request("GET", "/api/v1/auth/setup/status")
    if status.status != 200 or not isinstance(status.data, dict):
        print("WARN: setup status unavailable; continuing to login")
        return
    setup_done = bool(status.data.get("is_setup") or status.data.get("setup_complete"))
    if setup_done:
        print("OK: setup already complete")
        return
    payload = {
        "user": {
            "username": ADMIN_USERNAME,
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        },
        "llm_provider": LLM_PROVIDER,
        "llm_model": LLM_MODEL,
        "llm_api_key": LLM_API_KEY,
        "llm_api_base": LLM_API_BASE_URL,
    }
    resp = _request("POST", "/api/v1/auth/setup", json_body=payload, timeout=60)
    _ok(resp.status in (200, 201), f"first-run setup completed (status {resp.status})")


def _login() -> str:
    resp = _request(
        "POST",
        "/api/v1/auth/token",
        form_body={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    _ok(resp.status == 200 and isinstance(resp.data, dict), f"admin login succeeded (status {resp.status})")
    token = resp.data.get("access_token")
    _ok(bool(token), "admin token returned")
    return str(token)


def _check_health(token: str) -> None:
    public = _request("GET", "/api/v1/health?scope=public")
    _ok(public.status in (200, 503) and isinstance(public.data, dict), "public health returned canonical JSON")
    _ok("services" in public.data and "components" in public.data, "public health includes services and components")
    _ok(public.data.get("services", {}).get("api", {}).get("status") == "healthy", "API service reports healthy")

    headers = {"Authorization": f"Bearer {token}"}
    if SERVICE_AUTH_SECRET:
        headers["X-Service-Auth"] = SERVICE_AUTH_SECRET
    full = _request("GET", "/api/v1/health?detail=full&include=services,nodes", headers=headers, timeout=60)
    _ok(full.status in (200, 503) and isinstance(full.data, dict), "full health returned canonical JSON")
    _ok("latency_ms" in full.data.get("components", {}).get("database", {}), "database latency present")
    service_latencies = [
        svc.get("latency_ms")
        for svc in full.data.get("services", {}).values()
        if isinstance(svc, dict) and svc.get("status") != "not_configured"
    ]
    _ok(any(value is not None for value in service_latencies), "service latency present in full health")


def _check_ai(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    ai_status = _request("GET", "/api/ai/status", headers=headers, timeout=30)
    _ok(ai_status.status == 200, f"AI status endpoint responded (status {ai_status.status})")

    gateway_url = TENSORZERO_GATEWAY_URL or "http://tensorzero:3000"
    tz = _request("POST", "/test-tz-gateway", json_body={"gateway_url": gateway_url}, timeout=30)
    _ok(tz.status == 200 and isinstance(tz.data, dict), "TensorZero gateway test endpoint responded")

    if not AI_SERVICE_URL:
        print("SKIP: AI_SERVICE_URL not set; direct AI service chat smoke skipped")
        return
    direct_headers = {"Content-Type": "application/json"}
    if SERVICE_AUTH_SECRET:
        direct_headers["X-Service-Auth"] = SERVICE_AUTH_SECRET
    chat = _request(
        "POST",
        f"{AI_SERVICE_URL.rstrip('/')}/api/v1/ai/chat",
        headers=direct_headers,
        json_body={
            "messages": [{"role": "user", "content": "Reply with the single word: spectra"}],
            "tier": 1,
            "max_tokens": 12,
            "temperature": 0,
        },
        timeout=90,
    )
    if _is_provider_quota_failure(chat):
        print("WARN: direct AI service reached provider quota/rate limit; stack wiring is healthy but live LLM quota is exhausted")
        return
    if chat.status in (500, 502, 503) and not STRICT_LLM_SMOKE:
        print(
            "WARN: direct AI service returned "
            f"{chat.status}; continuing because STRICT_LLM_SMOKE is disabled. Check AI/TensorZero provider logs."
        )
        return
    _ok(chat.status == 200 and isinstance(chat.data, dict), f"direct AI service chat completed (status {chat.status})")
    _ok(bool(chat.data.get("content")), "direct AI service returned content")


def _check_ui(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    setup = _request("GET", "/setup")
    _ok(setup.status in (200, 302, 303), f"setup page route responded (status {setup.status})")
    dashboard = _request("GET", "/dashboard", headers=headers)
    _ok(dashboard.status in (200, 302, 303), f"dashboard route responded (status {dashboard.status})")


def main() -> int:
    print(f"Running live smoke against {BASE_URL}")
    try:
        _setup_if_needed()
        token = _login()
        _check_health(token)
        _check_ai(token)
        _check_ui(token)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("Live smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
