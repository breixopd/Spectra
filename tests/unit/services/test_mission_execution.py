"""Tests for MissionExecutionManager."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai_core.agents.base import AgentContext
from spectra_ai_core.agents.mission_controller import AssessmentPhase, MissionPlan, Task
from spectra_common.constants import MISSION_TIMEOUT_SECONDS
from spectra_mission.manager.execution import MissionExecutionManager
from spectra_mission.manager.helpers import _execute_task, execute_mission_tasks


@pytest.fixture
def execution_manager():
    lifecycle = MagicMock()
    lifecycle.initialize_mission = AsyncMock(return_value=MagicMock())
    lifecycle.update_db_status = AsyncMock()

    steering = MagicMock()

    mgr = MissionExecutionManager(lifecycle, steering)
    return mgr


class TestEnsureAgents:
    @pytest.mark.asyncio
    async def test_initializes_all_agents(self, execution_manager):
        with patch("spectra_mission.manager.execution.get_global_llm_client", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = AsyncMock()
            await execution_manager.ensure_agents()

        assert execution_manager.mission_controller is not None
        assert execution_manager.scope_agent is not None
        assert execution_manager.executor is not None
        assert execution_manager.consensus is not None


class TestMissionLoop:
    @pytest.mark.asyncio
    async def test_loop_returns_if_init_fails(self, execution_manager):
        execution_manager.lifecycle.initialize_mission = AsyncMock(return_value=None)

        mission = MagicMock()
        mission.record_demo = False

        await execution_manager.run_mission_loop(mission)
        # Should return early without errors

    @pytest.mark.asyncio
    async def test_loop_sets_status_on_exception(self, execution_manager):
        execution_manager.lifecycle.initialize_mission = AsyncMock(return_value=MagicMock())
        execution_manager._create_sandbox = AsyncMock()

        mission = MagicMock()
        mission.record_demo = False
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "test"
        mission.findings = []

        # Make scope phase fail
        execution_manager._run_scope_phase = AsyncMock(side_effect=RuntimeError("scope failed"))
        execution_manager._broadcast_state = MagicMock()

        with patch("spectra_mission.manager.execution.shell_manager"):
            with patch("spectra_system.notifications.notify_mission_started", new_callable=AsyncMock, create=True):
                await execution_manager.run_mission_loop(mission)

        mission.set_status.assert_called_with("failed")

    @pytest.mark.asyncio
    async def test_loop_demo_recorder_integration(self, execution_manager):
        execution_manager.lifecycle.initialize_mission = AsyncMock(return_value=MagicMock())
        execution_manager._create_sandbox = AsyncMock()

        mission = MagicMock()
        mission.record_demo = True
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "test"
        mission.findings = []
        mission.log = MagicMock()

        # Make scope phase fail to short-circuit
        execution_manager._run_scope_phase = AsyncMock(side_effect=RuntimeError("test"))
        execution_manager._broadcast_state = MagicMock()

        with patch("spectra_mission.manager.execution.shell_manager"):
            with patch("spectra_mission.demo_recorder.DemoRecorder") as MockRec:
                mock_rec = MockRec.return_value
                mock_rec.start = MagicMock()
                mock_rec.stop = MagicMock()
                mock_rec.save = AsyncMock()
                mock_rec.is_recording = True
                mock_rec.event_count = 2

                await execution_manager.run_mission_loop(mission)

                mock_rec.start.assert_called_once()
                mock_rec.stop.assert_called_once()
                mock_rec.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_loop_success_path(self, execution_manager):
        context = MagicMock()
        execution_manager.lifecycle.initialize_mission = AsyncMock(return_value=context)
        execution_manager._create_sandbox = AsyncMock()

        mission = MagicMock()
        mission.record_demo = False
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "test"
        mission.findings = [{"severity": "high"}]
        mission.plan = MagicMock()
        mission.user_id = None

        execution_manager._run_scope_phase = AsyncMock()
        execution_manager._run_planning_phase = AsyncMock()
        execution_manager._execute_mission_tasks = AsyncMock()
        execution_manager._record_mission_lessons = MagicMock()
        execution_manager._run_debrief = AsyncMock()
        execution_manager._generate_html_report = AsyncMock()
        execution_manager._broadcast_state = MagicMock()
        execution_manager._llm_provider_healthy = AsyncMock(return_value=True)

        with patch("spectra_mission.manager.execution.shell_manager"):
            with patch("spectra_system.notifications.notify_mission_started", new_callable=AsyncMock, create=True):
                with patch("spectra_mission.manager.execution.index_to_rag", new_callable=AsyncMock):
                    await execution_manager.run_mission_loop(mission)

        mission.set_status.assert_called_with("completed")

    @pytest.mark.asyncio
    async def test_loop_no_plan_fails(self, execution_manager):
        context = MagicMock()
        execution_manager.lifecycle.initialize_mission = AsyncMock(return_value=context)
        execution_manager._create_sandbox = AsyncMock()

        mission = MagicMock()
        mission.record_demo = False
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "test"
        mission.findings = []
        mission.plan = None  # No plan created
        mission.user_id = None

        execution_manager._run_scope_phase = AsyncMock()
        execution_manager._run_planning_phase = AsyncMock()
        execution_manager._broadcast_state = MagicMock()

        with patch("spectra_mission.manager.execution.shell_manager"):
            await execution_manager.run_mission_loop(mission)

        mission.set_status.assert_called_with("failed")


class TestScopePhase:
    @pytest.mark.asyncio
    async def test_scope_calls_agent(self, execution_manager):
        execution_manager.scope_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.action = MagicMock()
        mock_result.action.targets = ["10.0.0.1"]
        execution_manager.scope_agent.execute = AsyncMock(return_value=mock_result)
        execution_manager._broadcast_state = MagicMock()

        mission = MagicMock()
        mission.target = "10.0.0.1"
        context = MagicMock()

        await execution_manager._run_scope_phase(mission, context)

        execution_manager.scope_agent.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scope_failure_raises(self, execution_manager):
        execution_manager.scope_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Invalid target"
        execution_manager.scope_agent.execute = AsyncMock(return_value=mock_result)
        execution_manager._broadcast_state = MagicMock()

        mission = MagicMock()
        mission.target = "bad"
        context = MagicMock()

        with pytest.raises(RuntimeError, match="Scoping failed"):
            await execution_manager._run_scope_phase(mission, context)

    @pytest.mark.asyncio
    async def test_scope_not_initialized_raises(self, execution_manager):
        execution_manager.scope_agent = None
        execution_manager._broadcast_state = MagicMock()

        mission = MagicMock()
        context = MagicMock()

        with pytest.raises(RuntimeError, match="Scope agent not initialized"):
            await execution_manager._run_scope_phase(mission, context)


class TestPlanningPhase:
    @pytest.mark.asyncio
    async def test_planning_not_initialized_raises(self, execution_manager):
        execution_manager.mission_controller = None

        mission = MagicMock()
        context = MagicMock()

        with pytest.raises(RuntimeError, match="Mission controller not initialized"):
            await execution_manager._run_planning_phase(mission, context)


class TestTaskExecutionHelpers:
    @pytest.mark.asyncio
    async def test_execute_mission_tasks_stops_before_running_tasks(self):
        mission = MagicMock()
        mission.plan = MissionPlan(
            tasks=[
                Task(
                    task_id="t1",
                    description="enumerate target",
                    agent_type="agent1",
                    phase=AssessmentPhase.DISCOVERY,
                )
            ]
        )
        mission.findings = []
        mission.skipped_phases = set()
        mission.is_stopped.return_value = True
        mission.wait_if_paused = AsyncMock()
        mission.log = MagicMock()

        context = AgentContext(
            mission_id="mission-1",
            session_id="session-1",
            target="10.0.0.1",
            mission="test",
        )
        executor = MagicMock()
        executor.execute_task = AsyncMock()
        lifecycle = MagicMock()
        lifecycle.update_db_status = AsyncMock()
        lifecycle.save_checkpoint = AsyncMock()

        await execute_mission_tasks(
            mission,
            context,
            executor,
            None,
            None,
            MagicMock(),
            lifecycle,
        )

        executor.execute_task.assert_not_awaited()
        mission.wait_if_paused.assert_not_awaited()
        mission.log.assert_any_call("Mission stopped by user")

    @pytest.mark.asyncio
    async def test_execute_mission_tasks_times_out_before_running_tasks(self):
        mission = MagicMock()
        mission.plan = MissionPlan(
            tasks=[
                Task(
                    task_id="t1",
                    description="enumerate target",
                    agent_type="agent1",
                    phase=AssessmentPhase.DISCOVERY,
                )
            ]
        )
        mission.findings = []
        mission.skipped_phases = set()
        mission.is_stopped.return_value = False
        mission.wait_if_paused = AsyncMock()
        mission.log = MagicMock()
        mission.set_status = MagicMock()
        mission._start_wall_time = time.time() - MISSION_TIMEOUT_SECONDS - 1

        context = AgentContext(
            mission_id="mission-1",
            session_id="session-1",
            target="10.0.0.1",
            mission="test",
        )
        executor = MagicMock()
        executor.execute_task = AsyncMock()
        lifecycle = MagicMock()
        lifecycle.update_db_status = AsyncMock()
        lifecycle.save_checkpoint = AsyncMock()

        await execute_mission_tasks(
            mission,
            context,
            executor,
            None,
            None,
            MagicMock(),
            lifecycle,
        )

        executor.execute_task.assert_not_awaited()
        mission.set_status.assert_called_once_with("timed_out")
        assert any("[TIMEOUT] Mission timed out after" in call.args[0] for call in mission.log.call_args_list)

    @pytest.mark.asyncio
    async def test_execute_task_copies_context_for_parallel_tasks(self):
        task = Task(
            task_id="t1",
            description="exploit target",
            agent_type="agent1",
            phase=AssessmentPhase.EXPLOITATION,
        )
        mission = MagicMock()
        mission.plan = MissionPlan(tasks=[task])
        mission.log = MagicMock()
        executor = MagicMock()
        executor.execute_task = AsyncMock()
        context = AgentContext(
            mission_id="mission-1",
            session_id="session-1",
            target="10.0.0.1",
            mission="test",
            phase=AssessmentPhase.DISCOVERY.value,
        )

        await _execute_task(
            mission,
            executor,
            0,
            task,
            context,
            copy_context=True,
        )

        passed_context = executor.execute_task.await_args.args[2]
        assert passed_context is not context
        assert passed_context.phase == AssessmentPhase.EXPLOITATION.value
        assert context.phase == AssessmentPhase.DISCOVERY.value

    @pytest.mark.asyncio
    async def test_execute_task_mutates_shared_context_for_dependent_tasks(self):
        task = Task(
            task_id="t1",
            description="write report",
            agent_type="agent1",
            phase=AssessmentPhase.REPORTING,
        )
        mission = MagicMock()
        mission.plan = MissionPlan(tasks=[task])
        mission.log = MagicMock()
        executor = MagicMock()
        executor.execute_task = AsyncMock()
        context = AgentContext(
            mission_id="mission-1",
            session_id="session-1",
            target="10.0.0.1",
            mission="test",
            phase=AssessmentPhase.DISCOVERY.value,
        )

        await _execute_task(
            mission,
            executor,
            0,
            task,
            context,
            copy_context=False,
        )

        passed_context = executor.execute_task.await_args.args[2]
        assert passed_context is context
        assert context.phase == AssessmentPhase.REPORTING.value
