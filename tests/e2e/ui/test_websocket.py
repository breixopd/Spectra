"""WebSocket real-time update tests — verify connection, auth, and dashboard UI updates."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ui.harness.db_user import (
    create_verified_test_user,
    ui_login,
)
from tests.e2e.ui.harness.navigation import goto_authenticated_app_path

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _wait_for_sidebar_hydration(page: Page) -> None:
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)
    page.wait_for_function(
        """() => {
            const u = document.getElementById('sidebar-username');
            return u && u.textContent && u.textContent.trim().length > 0;
        }""",
        timeout=20_000,
    )


@pytest.mark.timeout(60)
def test_websocket_connects_and_pongs(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    result = page.evaluate("""
        async () => {
            const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
            const token = document.cookie.match(/access_token=([^;]+)/)?.[1];
            const ws = new WebSocket(`${wsUrl}?token=${token}`);
            return new Promise((resolve) => {
                let resolved = false;
                const done = (val) => { if (!resolved) { resolved = true; resolve(val); } };
                ws.onopen = () => { ws.send(JSON.stringify({type: 'ping'})); };
                ws.onmessage = (e) => {
                    try {
                        const msg = JSON.parse(e.data);
                        if (msg.type === 'pong') {
                            done({ok: true, message: e.data});
                        }
                    } catch (_) {
                        done({ok: true, message: e.data});
                    }
                };
                ws.onerror = () => done({ok: false, error: 'websocket error'});
                ws.onclose = () => done({ok: false, error: 'websocket closed'});
                setTimeout(() => done({ok: false, error: 'timeout'}), 10000);
            });
        }
    """)
    assert result.get("ok"), f"WebSocket connection failed: {result.get('error')}"


@pytest.mark.timeout(60)
def test_websocket_receives_mission_status_update(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    before = page.locator("#status-text").inner_text()

    page.evaluate("""
        () => {
            const event = new CustomEvent('spectra:ws-message', {
                detail: JSON.stringify({
                    type: 'agent_state',
                    data: { agent_id: 'recon_intel', status: 'running' }
                })
            });
            document.dispatchEvent(event);
        }
    """)

    expect(page.locator("#status-text")).not_to_have_text(before, timeout=5_000)
    status = page.locator("#status-text").inner_text()
    assert "running" in status.lower(), f"Expected status to contain 'running', got: {status}"


@pytest.mark.timeout(60)
def test_websocket_log_message_appears_in_activity_log(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    page.evaluate("""
        () => {
            const event = new CustomEvent('spectra:ws-message', {
                detail: JSON.stringify({
                    type: 'log',
                    data: 'E2E test log entry from websocket'
                })
            });
            document.dispatchEvent(event);
        }
    """)

    terminal = page.locator("#terminal-output")
    expect(terminal).to_contain_text("E2E test log entry from websocket", timeout=5_000)


@pytest.mark.timeout(60)
def test_websocket_unauthorized_connection_rejected(page: Page, app_url: str) -> None:
    result = page.evaluate("""
        async () => {
            const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
            const ws = new WebSocket(`${wsUrl}?token=invalid_token`);
            return new Promise((resolve) => {
                let resolved = false;
                const done = (val) => { if (!resolved) { resolved = true; resolve(val); } };
                ws.onclose = (e) => done({closed: true, code: e.code, reason: e.reason});
                ws.onerror = () => done({closed: true, code: null, reason: 'error'});
                setTimeout(() => done({closed: false, reason: 'timeout'}), 10000);
            });
        }
    """)
    assert result.get("closed"), "Unauthorized WebSocket should have been closed"
    assert result.get("code") == 4001 or result.get("reason") == "error", (
        f"Expected 4001 auth close, got: {result}"
    )
