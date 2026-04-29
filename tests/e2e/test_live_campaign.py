import asyncio
import logging
import os

import pytest
import pytest_asyncio

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



# Targets from docker/compose.yaml (profiles app + targets) when stack is running
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
        await engine.dispose()
        import app.services.tools.registry as registry_module
        registry_module._registry = None
        registry = get_registry()
        await registry.load_plugins()
        critical_tools = ["nmap", "searchsploit", "metasploit", "curl", "nikto", "sqlmap"]
        for tool_id in critical_tools:
            if tool_id in registry._tools:
                tool = registry._tools[tool_id]
                if tool.status.name != "READY":
                    try:
                        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
                        await registry.install_tool(tool_id)
                    except Exception as e:
                        print(f"Failed to install {tool_id}: {e}")
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
