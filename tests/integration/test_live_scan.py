"""
Live integration tests against Spectra vulnerable test targets.

Requires:
    - spectra-app running (SPECTRA_URL env or http://app:5000)
    - Vulnerable targets on spectra-network (vuln-web, vuln-ssh, vuln-network)
    - spectra-tools container with nmap available

Run via:
    ./tests/run_live_tests.sh

Or manually:
    pytest tests/integration/test_live_scan.py -v -m live --timeout=120
"""

import os

import httpx
import pytest

pytestmark = [pytest.mark.live]

SPECTRA_URL = os.getenv("SPECTRA_URL", "http://app:5000")
VULN_WEB_HOST = os.getenv("VULN_WEB_HOST", "spectra-vuln-web")
VULN_SSH_HOST = os.getenv("VULN_SSH_HOST", "spectra-vuln-ssh")
VULN_NETWORK_HOST = os.getenv("VULN_NETWORK_HOST", "spectra-vuln-network")
TOOL_TEST_ENDPOINT_TEMPLATE = "/api/v1/tools/{tool_id}/test"
MISSION_START_ENDPOINT = "/api/v1/missions"


@pytest.fixture(scope="module")
def auth_headers():
    """Authenticate against the running Spectra instance."""
    with httpx.Client(base_url=SPECTRA_URL, timeout=30) as client:
        status = client.get("/api/v1/auth/setup/status")
        if status.status_code == 200 and not status.json().get("is_setup"):
            client.post(
                "/api/v1/auth/setup",
                json={
                    "user": {
                        "username": "admin",
                        "email": "admin@spectra.local",
                        "password": "Admin123!",
                    },
                    "llm_provider": os.getenv("AI_PROVIDER", "mock"),
                    "llm_model": os.getenv("LLM_MODEL", ""),
                    "llm_api_key": os.getenv("LLM_API_KEY", ""),
                },
            )
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": "admin", "password": "Admin123!"},
        )
        assert resp.status_code == 200, f"Auth failed: {resp.text}"
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="module")
def client():
    return httpx.Client(base_url=SPECTRA_URL, timeout=130)


def _run_tool_test(
    client: httpx.Client,
    auth_headers: dict[str, str],
    *,
    tool_id: str,
    target: str,
    args: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"target": target}
    if args is not None:
        payload["args"] = args
    if timeout is not None:
        payload["timeout"] = timeout

    resp = client.post(
        TOOL_TEST_ENDPOINT_TEMPLATE.format(tool_id=tool_id),
        headers=auth_headers,
        json=payload,
    )
    assert resp.status_code == 200, f"Tool test failed: {resp.text}"
    return resp.json()


# ── Network scanning tests ──────────────────────────────────


class TestNetworkScan:
    """Verify nmap can discover open ports on vuln-network."""

    @pytest.mark.live
    def test_nmap_discovers_open_ports(self, client, auth_headers):
        """Submit a scan job against vuln-network and verify port discovery."""
        data = _run_tool_test(
            client,
            auth_headers,
            tool_id="nmap",
            target=VULN_NETWORK_HOST,
            args={"ports": "21,80,443,3306", "flags": "--open"},
            timeout=120,
        )
        assert data["tool_id"] == "nmap"
        assert data["success"] is True, data
        stdout = str(data.get("stdout") or "")
        assert data.get("parsed_findings_count", 0) > 0 or "open" in stdout.lower(), data

    @pytest.mark.live
    def test_nmap_finds_ssh_on_vuln_ssh(self, client, auth_headers):
        """Verify SSH port is detected on vuln-ssh target."""
        data = _run_tool_test(
            client,
            auth_headers,
            tool_id="nmap",
            target=VULN_SSH_HOST,
            args={"ports": "22", "flags": "--open"},
            timeout=120,
        )
        assert data["success"] is True, data
        stdout = str(data.get("stdout") or "")
        assert "22/tcp" in stdout.lower() or "ssh" in stdout.lower() or data.get("parsed_findings_count", 0) > 0, data


# ── Web vulnerability tests ─────────────────────────────────


class TestWebScan:
    """Verify web vulnerabilities on vuln-web are detectable."""

    @pytest.mark.live
    def test_xss_detection_on_vuln_web(self, client, auth_headers):
        """Check that XSS-vulnerable search endpoint reflects input."""
        # Also do a direct HTTP call to the target if reachable
        try:
            target_resp = httpx.get(
                f"http://{VULN_WEB_HOST}/search?q=<script>alert(1)</script>",
                timeout=10,
            )
            assert "<script>alert(1)</script>" in target_resp.text, "XSS payload should be reflected unescaped"
        except httpx.ConnectError:
            pytest.skip("Cannot reach vuln-web directly from test runner")

    @pytest.mark.live
    def test_sqli_endpoint_exists(self, client, auth_headers):
        """Verify the SQL injection endpoint is accessible."""
        try:
            resp = httpx.get(
                f"http://{VULN_WEB_HOST}/user?id=1%20OR%201=1",
                timeout=10,
            )
            assert resp.status_code == 200
            assert "Results:" in resp.text or "Error:" in resp.text
        except httpx.ConnectError:
            pytest.skip("Cannot reach vuln-web directly from test runner")

    @pytest.mark.live
    def test_admin_default_credentials(self, client, auth_headers):
        """Verify default credentials work on vuln-web admin panel."""
        try:
            resp = httpx.post(
                f"http://{VULN_WEB_HOST}/admin",
                data={"user": "admin", "pass": "admin123"},
                timeout=10,
            )
            assert "Welcome, admin!" in resp.text
        except httpx.ConnectError:
            pytest.skip("Cannot reach vuln-web directly from test runner")


# ── Mission engine tests ────────────────────────────────────


class TestMissionEngine:
    """Verify mission creation against live targets."""

    @pytest.mark.live
    def test_create_mission_against_target(self, client, auth_headers):
        """Create a mission targeting vuln-network and verify it's accepted."""
        resp = client.post(
            MISSION_START_ENDPOINT,
            headers=auth_headers,
            json={
                "target": VULN_NETWORK_HOST,
                "directive": "Perform a reconnaissance scan and identify exposed network services.",
            },
        )
        assert resp.status_code in (200, 201, 202), f"Mission creation failed: {resp.text}"
        data = resp.json()
        assert "id" in data, "Mission response should include an ID"
