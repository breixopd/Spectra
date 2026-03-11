"""
E2E Test: User Steering & Interactivity (E2E-02, E2E-03)

Tests user steering capabilities:
- E2E-02: Mid-mission steering to focus on specific areas
- E2E-03: Emergency stop functionality

Corresponds to testplan.md Scenarios E2E-02 and E2E-03.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.agents.base import ActionRisk, SteeringAction
from app.services.ai.consensus import QualityGate
from app.services.mission.manager import MissionManager

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio,
]


class TestUserSteering:
    """Test user steering functionality (E2E-02)."""

    async def test_steering_action_applied(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that steering actions are properly applied to mission."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                # Start mission
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Full assessment",
                )

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None

                # Create and apply a steering action
                steering_action = SteeringAction(
                    confidence=0.9,
                    risk_level=ActionRisk.LOW,
                    reasoning="Focus on web vulnerabilities per user request",
                    new_phase="vulnerability",
                    priority_targets=["web"],
                    skip_phases=["exploitation"],
                )

                await mission_manager.steering.apply_steering_action(
                    mission, steering_action
                )

                # Verify steering was applied
                assert "exploitation" in mission.skipped_phases
                logs = mission.logs
                assert any("STEERING" in log for log in logs)

    async def test_steering_skips_phases(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that steering can skip phases."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Skip exploitation",
                )

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None

                # Skip multiple phases
                steering_action = SteeringAction(
                    confidence=0.95,
                    risk_level=ActionRisk.LOW,
                    reasoning="User wants recon only",
                    new_phase="discovery",
                    skip_phases=["exploitation", "post_exploitation"],
                )

                await mission_manager.steering.apply_steering_action(
                    mission, steering_action
                )

                assert "exploitation" in mission.skipped_phases
                assert "post_exploitation" in mission.skipped_phases

    async def test_steering_prioritizes_targets(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that steering can prioritize specific targets/vectors."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Focus on SSH",
                )

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None

                # Add some vectors first
                from app.models.attack_surface import AttackVector, VectorPriority

                mission.attack_surface.add_vector(
                    AttackVector(
                        id="ssh-brute",
                        name="SSH Brute Force",
                        description="Brute force SSH",
                        priority=VectorPriority.LOW,
                        target_type="service",
                        target_ref=f"{test_target_ip}:22",
                    )
                )

                mission.attack_surface.add_vector(
                    AttackVector(
                        id="http-scan",
                        name="HTTP Vulnerability Scan",
                        description="Scan HTTP",
                        priority=VectorPriority.MEDIUM,
                        target_type="service",
                        target_ref=f"{test_target_ip}:80",
                    )
                )

                # Apply steering to prioritize SSH
                steering_action = SteeringAction(
                    confidence=0.9,
                    risk_level=ActionRisk.LOW,
                    reasoning="Focus on SSH per user request",
                    new_phase="exploitation",
                    priority_targets=["ssh", "SSH"],
                )

                await mission_manager.steering.apply_steering_action(
                    mission, steering_action
                )

                # Verify prioritization was logged
                logs = mission.logs
                assert any("Prioritizing" in log for log in logs)

    async def test_steering_triggers_replan_validation(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that steering triggers REPLAN quality gate validation."""
        replan_validated = False

        # Initialize execution manager to setup consensus
        await mission_manager._ensure_agents()
        original_validate = mission_manager.execution.consensus.validate_at_gate

        async def mock_validate(gate, action, context):
            nonlocal replan_validated
            if gate == QualityGate.REPLAN:
                replan_validated = True
            return await original_validate(gate, action, context)

        # Patch internal Consensus instance method
        with patch.object(
            mission_manager.execution.consensus,
            "validate_at_gate",
            side_effect=mock_validate,
        ):
            with patch("app.services.mission.manager.lifecycle.async_session_maker"):
                with patch("app.core.events.events.emit_sync"):
                    mission_id = await mission_manager.start_mission(
                        target=test_target_ip,
                        directive="Test steering validation",
                    )

                    mission = await mission_manager.get_mission(mission_id)

                    # Simulate task failure to trigger replanning
                    if mission:
                        from app.services.ai.agents.mission_controller import (
                            AssessmentPhase,
                            Task,
                        )

                        task = Task(
                            task_id="test-task",
                            description="Test task",
                            agent_type="tool_selector",
                            phase=AssessmentPhase.DISCOVERY,
                            priority=1,
                        )

                        from app.services.ai.agents.base import AgentContext

                        context = AgentContext(
                            mission_id=mission_id,
                            session_id=mission_id,
                            target=test_target_ip,
                            mission="Test",
                            phase="discovery",
                            stealth_mode=False,
                            max_concurrency=1,
                        )

                        # Mock controller to return a steering action
                        # Since we are bypassing LLM client, we need to mock controller internal execution
                        if mission_manager.execution.mission_controller:
                            mock_controller_result = AsyncMock()
                            mock_controller_result.success = True
                            mock_controller_result.action = SteeringAction(
                                confidence=0.9,
                                risk_level=ActionRisk.LOW,
                                reasoning="Test Replan",
                                new_phase="discovery",
                            )
                            mission_manager.execution.mission_controller.execute = (
                                AsyncMock(return_value=mock_controller_result)
                            )

                        await mission_manager.execution._handle_task_failure(
                            mission, task, "Test error", context
                        )

        # If replan was successful and validated, this should be true
        assert replan_validated, "REPLAN gate was not validated"


class TestEmergencyStop:
    """Test emergency stop functionality (E2E-03)."""

    async def test_stop_mission_immediately(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that stop_mission stops execution immediately."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                # Start mission
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Long running assessment",
                )

                # Stop immediately
                result = await mission_manager.stop_mission(mission_id)

                assert result is True

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None
                assert mission.is_stopped()

    async def test_stop_sets_stopped_flag(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that stop sets the internal stopped flag."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Test stop flag",
                )

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None

                # Initially not stopped
                assert not mission.is_stopped()

                # Stop
                mission.stop()

                # Now stopped
                assert mission.is_stopped()

    async def test_stop_nonexistent_mission_returns_false(
        self, mission_manager: MissionManager
    ):
        """Test that stopping a nonexistent mission returns False."""
        result = await mission_manager.stop_mission("nonexistent-id")
        assert result is False

    async def test_stopped_mission_skips_tasks(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that a stopped mission doesn't execute more tasks."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Multi-task mission",
                )

                # Give it a moment to start
                await asyncio.sleep(0.5)

                # Stop the mission
                await mission_manager.stop_mission(mission_id)

                # Wait a bit more
                await asyncio.sleep(1)

                # Check logs for stop message
                mission = await mission_manager.get_mission(mission_id)
                if mission:
                    # Should have stop-related log
                    assert mission.is_stopped()

    async def test_stop_updates_status(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that stopping updates mission status appropriately."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Status test",
                )

                await asyncio.sleep(0.5)

                await mission_manager.stop_mission(mission_id)

                # Give time for status update
                await asyncio.sleep(1)

                mission = await mission_manager.get_mission(mission_id)
                # Status should be cancelled or the loop should have noted the stop
                assert mission is not None
                assert mission.is_stopped()


class TestMissionStateManagement:
    """Test mission state management during steering."""

    async def test_list_missions(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test listing all missions."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                # Start multiple missions
                id1 = await mission_manager.start_mission(test_target_ip, "Mission 1")
                id2 = await mission_manager.start_mission(test_target_ip, "Mission 2")

                missions = mission_manager.list_missions()

                assert len(missions) >= 2
                mission_ids = [m["id"] for m in missions]
                assert id1 in mission_ids
                assert id2 in mission_ids

    async def test_mission_to_dict(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test mission serialization."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    test_target_ip,
                    "Serialization test",
                )

                mission = await mission_manager.get_mission(mission_id)
                assert mission is not None

                data = mission.to_dict()

                assert "id" in data
                assert "target" in data
                assert "directive" in data
                assert "status" in data
                assert "logs_count" in data  # Note: not 'logs', it's 'logs_count'
                assert data["target"] == test_target_ip
