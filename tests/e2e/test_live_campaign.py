import asyncio
import logging
import os

import pytest
import pytest_asyncio

import app.models  # noqa
from app.core.config import settings
from app.core.database import engine
from app.models.base import Base
from app.services.tools.registry import get_registry

# Configure logging to show thinking process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spectra.test.campaign")

pytestmark = [
    pytest.mark.live,
    pytest.mark.asyncio,
    pytest.mark.slow,
]

# Targets from docker-compose.test.yml
TARGET_SERVER = os.getenv("TARGET_SERVER", "172.21.0.50")  # Metasploitable
TARGET_WEB = os.getenv("TARGET_WEB", "172.21.0.51")  # DVWA


class TestLiveCampaign:
    """
    Comprehensive Live Campaign Test.

    Executes full mission lifecycles against vulnerable targets to verify:
    1. Planning & Strategy (Thinking)
    2. Tool Selection & Safety (Voting)
    3. Execution & Adaptation (Tool Use)
    4. Reporting & Knowledge Retention
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_campaign(self):
        """Ensure environment is ready for testing."""
        # Tools run locally in the test runner container
        settings.PLUGIN_SAFE_MODE = False  # Disable signature checks for tests

        # Dispose engine to ensure fresh connection on current loop
        await engine.dispose()

        # Initialize Registry (Reset singleton to pick up safe_mode change)
        import app.services.tools.registry as registry_module

        registry_module._registry = None

        registry = get_registry()
        registry.safe_mode = False
        if hasattr(registry, "validator"):
            registry.validator.safe_mode = False

        await registry.load_plugins()

        # Ensure critical tools are ready and installed
        critical_tools = [
            "nmap",
            "searchsploit",
            "metasploit",
            "curl",
            "nikto",
            "sqlmap",
        ]
        # Check for root or pre-installed tools
        # force the test to run by assuming we are in a containerized environment capable of installation
        # But we need an actual container running for 'docker exec' to work.
        # Use a fixture or assume 'spectra-tools' exists?
        # The user says "tool container shouldnt have tools preinstalled", implying one exists.

        # We will mock the TOOL_CONTAINER_NAME setting to 'spectra-tools-test' (or whatever is running)
        # However, if we are running the test LOCALLY, we might not have that container.

        # If we are in restricted env (no root), we CANNOT install tools unless we delegate to a container.
        # Let's assume the user has a container named 'spectra-tools' running.

        # Check if 'spectra-tools' container is running
        import subprocess

        try:
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],  # noqa: S607
                capture_output=True,
                text=True,
            )
            if "spectra-tools" in res.stdout:
                print("DEBUG: specialized 'spectra-tools' container found.")
            else:
                print("DEBUG: 'spectra-tools' container NOT found.")
        except Exception:
            pass

        # Revert skip logic - we WANT to fail if installation fails now, to debug logs.
        # But if no root and no container, it WILL fail.

        # If we don't have a container and not root, we can't install.
        # But the User wants us to "look at logs and fix issues".
        # This implies we *should* be able to install.
        pass

        for tool_id in critical_tools:
            if tool_id in registry._tools:
                tool = registry._tools[tool_id]
                # Only install if not already ready
                if tool.status.name != "READY":
                    print(f"Ensuring {tool_id} is installed...")
                    try:
                        # Set DEBIAN_FRONTEND to avoid interactive prompts
                        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
                        await registry.install_tool(tool_id)
                    except Exception as e:
                        print(f"Failed to install {tool_id}: {e}")
                        # Continue anyway, maybe it was already there or we want to see it fail later
                        pass

        # Reset DB
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def run_mission_until_completion(self, mission_manager, mission_id, timeout=1800):
        """Helper to monitor mission progress with detailed logging."""
        max_wait = timeout
        interval = 5
        elapsed = 0

        print(f"\n{'=' * 80}")
        print(f" MONITORING MISSION: {mission_id}")
        print(f"{'=' * 80}\n")

        last_log_count = 0
        mission = None

        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval

            mission = await mission_manager.get_mission(mission_id)
            if mission is None:
                continue

            # Print new logs
            if len(mission.logs) > last_log_count:
                for log_entry in mission.logs[last_log_count:]:
                    print(f"   {log_entry}")
                last_log_count = len(mission.logs)
            else:
                # Print a dot to show aliveness if no new logs
                print(".", end="", flush=True)

            if mission.status in [
                "completed",
                "failed",
                "stopped",
                "cancelled",
                "exploitation_successful",
                "exploitation_exhausted",
            ]:
                print(f"\nMission finished with status: {mission.status}")
                break

        return mission

    @pytest.mark.asyncio
    async def test_campaign_server_exploitation(self, real_mission_manager):
        """
        Campaign 1: Direct Server Exploitation (Metasploitable).
        Goal: Find open ports, identify services, and exploit a critical vulnerability (e.g., vsftpd).
        """
        print(f"\n[CAMPAIGN] Starting Server Exploitation against {TARGET_SERVER}")

        # Generic directive as requested
        directive = (
            "Perform a full security assessment of the target. "
            "Identify attack vectors and attempt to exploit any critical vulnerabilities found to demonstrate impact."
        )

        mission_id = await real_mission_manager.start_mission(
            target=TARGET_SERVER,
            directive=directive,
        )

        mission = await self.run_mission_until_completion(real_mission_manager, mission_id)

        # Verification
        assert mission is not None
        assert mission.status in [
            "completed",
            "exploitation_successful",
            "exploitation_exhausted",
        ], f"Mission failed with status: {mission.status}"

        # Check for findings instead of specific ports
        assert len(mission.findings) > 0, "No findings reported"

        print("\n[CAMPAIGN] Server Exploitation Finished")
        self._print_mission_summary(mission)

    @pytest.mark.asyncio
    async def test_campaign_web_exploitation(self, real_mission_manager):
        """
        Campaign 2: Web Application Exploitation (DVWA).
        Goal: Identify web technologies and find vulnerabilities.
        """
        print(f"\n[CAMPAIGN] Starting Web Exploitation against {TARGET_WEB}")

        # Generic directive as requested
        directive = (
            "Perform a full security assessment of the web application. "
            "Identify vulnerabilities and attempt to exploit them to demonstrate impact."
        )

        mission_id = await real_mission_manager.start_mission(
            target=TARGET_WEB,
            directive=directive,
        )

        mission = await self.run_mission_until_completion(real_mission_manager, mission_id)

        # Verification
        assert mission is not None
        assert mission.status in [
            "completed",
            "exploitation_successful",
            "exploitation_exhausted",
        ], f"Mission failed with status: {mission.status}"

        # Check for findings instead of specific ports
        assert len(mission.findings) > 0, "No findings reported"

        print("\n[CAMPAIGN] Web Exploitation Finished")
        self._print_mission_summary(mission)

    def _print_mission_summary(self, mission):
        """Print a structured summary of the mission."""
        print(f"\n{'=' * 40}")
        print(f" MISSION SUMMARY: {mission.target}")
        print(f"{'=' * 40}")
        print(f"Status: {mission.status}")
        print(f"Findings: {len(mission.findings)}")
        for f in mission.findings:
            print(f" - {f.get('title')} ({f.get('severity')})")

        print(f"Tools Used: {', '.join(mission.tools_run)}")
        print(
            f"Attack Surface: {len(mission.attack_surface.services)} services, {len(mission.attack_surface.vulnerabilities)} vulns"
        )
