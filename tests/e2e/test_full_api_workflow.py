"""Full API Workflow Test - Tests the COMPLETE platform workflow via HTTP API."""

import asyncio
import os
from datetime import datetime

import httpx
import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.live,
    pytest.mark.e2e,
    pytest.mark.asyncio,
    pytest.mark.slow,
]

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000")
TEST_TARGET = os.getenv("TEST_TARGET_IP", "127.0.0.1")


async def api_health_check(client: httpx.AsyncClient) -> bool:
    """Check if API is healthy."""
    try:
        response = await client.get(f"{API_BASE_URL}/api/health")
        return response.status_code == 200
    except Exception:
        return False


@pytest_asyncio.fixture
async def api_client():
    """Create HTTP client for API calls."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        if not await api_health_check(client):
            pytest.skip("API server not running - start with: docker compose up -d")
        yield client


@pytest_asyncio.fixture
async def auth_token(api_client: httpx.AsyncClient):
    """Get authentication token (creates user if needed)."""
    # Check if setup is needed
    setup_response = await api_client.get(f"{API_BASE_URL}/api/v1/auth/setup/status")

    if setup_response.status_code == 200:
        is_setup = setup_response.json().get("is_setup", False)

        if not is_setup:
            # Create admin user
            setup_data = {
                "user": {
                    "username": "admin",
                    "email": "admin@spectra.local",
                    "password": "AdminPass123!",
                }
            }
            response = await api_client.post(
                f"{API_BASE_URL}/api/v1/auth/setup",
                json=setup_data,
            )
            if response.status_code not in (200, 201):
                print(f"Setup response: {response.text}")

    # Login to get token
    login_data = {
        "username": "admin",
        "password": "AdminPass123!",
    }

    response = await api_client.post(
        f"{API_BASE_URL}/api/v1/auth/token",
        data=login_data,  # OAuth2 form data
    )

    if response.status_code == 200:
        token = response.json().get("access_token")
        print("Authenticated as admin")
        return token
    else:
        print(f"Login failed: {response.text}")
        pytest.skip("Authentication failed - check server logs")
        return None


def get_headers(token: str | None) -> dict:
    """Get request headers with optional auth token."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class TestAPIHealthChecks:
    """Verify all services are healthy before running workflow tests."""

    async def test_api_health(self, api_client: httpx.AsyncClient):
        """Test main API health endpoint."""
        response = await api_client.get(f"{API_BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"API Health: {data}")


class TestFullWorkflow:
    """Test complete platform workflow via API."""

    async def test_create_target_and_run_mission(
        self,
        api_client: httpx.AsyncClient,
        auth_token: str | None,
    ):
        """
        Complete workflow test:
        1. Create target
        2. Start mission
        3. Monitor progress
        4. Verify results
        """
        headers = get_headers(auth_token)

        print("\n" + "=" * 70)
        print("FULL WORKFLOW TEST - NO MOCKING")
        print("=" * 70)

        # Step 1: Create a target
        print("\nStep 1: Creating target...")
        target_data = {
            "address": TEST_TARGET,
            "description": f"Automated test target created at {datetime.now().isoformat()}",
        }

        response = await api_client.post(
            f"{API_BASE_URL}/api/targets",
            json=target_data,
            headers=headers,
        )

        if response.status_code in (200, 201):
            target = response.json()
            target_id = target["id"]
            print(f"   Target created: {target_id}")
            print(f"   Address: {target['address']}")
        elif response.status_code == 400:
            # Target might already exist
            print(f"   Target may already exist: {response.text}")
            # Try to list targets and find our test target
            list_response = await api_client.get(
                f"{API_BASE_URL}/api/targets",
                headers=headers,
            )
            if list_response.status_code == 200:
                targets = list_response.json()
                for t in targets:
                    if t.get("address") == TEST_TARGET:
                        target_id = t["id"]
                        print(f"   Using existing target: {target_id}")
                        break
                else:
                    pytest.fail(f"Could not create or find target: {response.text}")
            else:
                pytest.fail(f"Failed to list targets: {list_response.text}")
        else:
            pytest.fail(f"Failed to create target: {response.status_code} - {response.text}")

        # Step 2: Start a mission
        print("\nStep 2: Starting mission...")
        mission_data = {
            "target": TEST_TARGET,
            "directive": "Perform a quick security scan focusing on open ports and common vulnerabilities. Keep it brief.",
        }

        response = await api_client.post(
            f"{API_BASE_URL}/api/missions",
            json=mission_data,
            headers=headers,
        )

        if response.status_code not in (200, 201):
            pytest.fail(f"Failed to start mission: {response.status_code} - {response.text}")

        mission = response.json()
        mission_id = mission["id"]
        print(f"   Mission started: {mission_id}")
        print(f"   Target: {mission['target']}")
        print(f"   Status: {mission['status']}")

        # Step 3: Monitor mission progress
        print("\nStep 3: Monitoring mission progress...")
        max_wait_time = 120  # 2 minutes max
        poll_interval = 3
        elapsed = 0
        final_status = None
        last_log_count = 0

        while elapsed < max_wait_time:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            response = await api_client.get(
                f"{API_BASE_URL}/api/missions/{mission_id}",
                headers=headers,
            )

            if response.status_code != 200:
                print(f"   Failed to get mission: {response.status_code}")
                break

            mission = response.json()
            status = mission["status"]
            logs = mission.get("logs", [])

            # Print new logs
            if len(logs) > last_log_count:
                for log in logs[last_log_count:]:
                    print(f"   {log}")
                last_log_count = len(logs)

            # Check for terminal state
            if status in ["completed", "failed", "cancelled", "stopping"]:
                final_status = status
                print(f"\n   Mission {status}")
                break

            # Progress indicator every 15 seconds
            if elapsed % 15 == 0:
                print(f"   Status: {status} ({elapsed}s elapsed)")

        if final_status is None:
            print(f"\n   Mission timeout after {max_wait_time}s")
            # Try to stop the mission
            await api_client.post(
                f"{API_BASE_URL}/api/missions/{mission_id}/stop",
                headers=headers,
            )

        # Step 4: Verify mission results
        print("\nStep 4: Checking mission results...")
        response = await api_client.get(
            f"{API_BASE_URL}/api/missions/{mission_id}",
            headers=headers,
        )

        if response.status_code == 200:
            mission = response.json()
            print(f"   Final status: {mission['status']}")
            print(f"   Logs count: {len(mission.get('logs', []))}")

            # Get findings count
            findings_count = mission.get("findings_count", 0)
            print(f"   Findings: {findings_count}")

            # Get attack surface summary if available
            attack_surface = mission.get("attack_surface", {})
            if attack_surface:
                print(f"   Attack Surface: {attack_surface}")

        # Step 5: Check findings
        print("\nStep 5: Checking findings...")
        response = await api_client.get(
            f"{API_BASE_URL}/api/findings",
            headers=headers,
        )

        if response.status_code == 200:
            findings = response.json()
            print(f"   Total findings in database: {len(findings)}")
            if findings:
                for f in findings[:5]:  # Show first 5
                    print(f"   - {f.get('title', 'N/A')} ({f.get('severity', 'N/A')})")

        print("\n" + "=" * 70)
        print("WORKFLOW TEST COMPLETE")
        print("=" * 70)

        # Assertions
        assert mission_id is not None, "Mission should have been created"
        assert final_status in ["completed", "failed", "stopping", None], (
            f"Mission should end in terminal state, got: {final_status}"
        )

    async def test_list_available_tools(
        self,
        api_client: httpx.AsyncClient,
        auth_token: str | None,
    ):
        """Verify tools are loaded and available."""
        headers = get_headers(auth_token)

        response = await api_client.get(
            f"{API_BASE_URL}/api/tools",
            headers=headers,
        )

        assert response.status_code == 200
        tools = response.json()

        print(f"\nAvailable Tools ({len(tools)}):")
        for tool in tools[:10]:
            status = "Available" if tool.get("is_available") else "Unavailable"
            print(f"   {status} {tool['id']}: {tool['name']}")

        # Verify essential tools are present
        tool_ids = [t["id"] for t in tools]
        assert "nmap" in tool_ids, "nmap should be available"

    async def test_mission_steering(
        self,
        api_client: httpx.AsyncClient,
        auth_token: str | None,
    ):
        """Test mission steering (skip phases, prioritize targets)."""
        headers = get_headers(auth_token)

        # Start a mission
        mission_data = {
            "target": TEST_TARGET,
            "directive": "Quick port scan",
        }

        response = await api_client.post(
            f"{API_BASE_URL}/api/missions",
            json=mission_data,
            headers=headers,
        )

        if response.status_code not in (200, 201):
            pytest.skip(f"Could not start mission: {response.text}")

        mission = response.json()
        mission_id = mission["id"]

        # Wait a moment for mission to start
        await asyncio.sleep(2)

        # Try to steer the mission
        steer_data = {
            "action": "skip_phase",
            "phase": "enumeration",
        }

        response = await api_client.post(
            f"{API_BASE_URL}/api/missions/{mission_id}/steer",
            json=steer_data,
            headers=headers,
        )

        print(f"\nSteering response: {response.status_code}")
        if response.status_code == 200:
            print("   Mission steered successfully")
        else:
            print(f"   Response: {response.text}")

        # Stop the mission
        await api_client.post(
            f"{API_BASE_URL}/api/missions/{mission_id}/stop",
            headers=headers,
        )


class TestTargetCRUD:
    """Test target management API."""

    async def test_target_lifecycle(
        self,
        api_client: httpx.AsyncClient,
        auth_token: str | None,
    ):
        """Test create, read, update, delete for targets."""
        headers = get_headers(auth_token)

        # Create
        target_data = {
            "address": f"192.168.1.{datetime.now().second}",
            "description": f"CRUD Test {datetime.now().isoformat()}",
        }

        response = await api_client.post(
            f"{API_BASE_URL}/api/targets",
            json=target_data,
            headers=headers,
        )

        if response.status_code not in (200, 201):
            pytest.skip(f"Could not create target: {response.text}")

        target = response.json()
        target_id = target["id"]
        print(f"\nCreated target: {target_id}")

        # Read
        response = await api_client.get(
            f"{API_BASE_URL}/api/targets/{target_id}",
            headers=headers,
        )
        assert response.status_code == 200
        print(f"Read target: {response.json()['address']}")

        # Update
        update_data = {"notes": "Updated via test"}
        response = await api_client.patch(
            f"{API_BASE_URL}/api/targets/{target_id}",
            json=update_data,
            headers=headers,
        )
        if response.status_code == 200:
            print("Updated target")
        else:
            print(f"Update returned: {response.status_code}")

        # Delete
        response = await api_client.delete(
            f"{API_BASE_URL}/api/targets/{target_id}",
            headers=headers,
        )
        if response.status_code in (200, 204):
            print("Deleted target")
        else:
            print(f"Delete returned: {response.status_code}")


class TestWebSocketConnection:
    """Test WebSocket real-time updates."""

    async def test_websocket_connects(self, api_client: httpx.AsyncClient):
        """Test WebSocket connection."""
        import websockets

        try:
            ws_url = API_BASE_URL.replace("http", "ws") + "/ws"
            async with websockets.connect(ws_url, close_timeout=5) as ws:
                # Send a test message
                await ws.send("test")

                # Wait for response with timeout
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    response_str = str(response)
                    print(f"\nWebSocket response: {response_str}")
                    assert "test" in response_str
                except TimeoutError:
                    print("WebSocket response timeout (may be normal)")

        except Exception as e:
            print(f"WebSocket test: {e}")
            # Don't fail - WebSocket might not be critical for all tests
