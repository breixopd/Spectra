import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.mission.manager import MissionManager
from app.services.mission.mission import Mission
from app.services.ai.agents.base import AgentContext, AgentResult, SteeringAction
from app.services.ai.agents.mission_controller import MissionInput, MissionPlan, Task, AssessmentPhase

@pytest.fixture
def mock_manager_context():
    # Patch dependencies at their SOURCE definition to avoid import alias issues
    # Patch dependencies WHERE THEY ARE USED to handle imports correctly
    with patch("app.services.mission.manager.execution.MissionExecutor") as MockExecutor, \
         patch("app.services.mission.manager.execution.MissionController") as MockController, \
         patch("app.services.mission.manager.execution.ScopeAgent") as MockScope, \
         patch("app.services.mission.manager.execution.VotingSystem") as MockVoting, \
         patch("app.services.mission.manager.lifecycle.MissionRepository") as MockRepo, \
         patch("app.services.mission.manager.execution.get_global_llm_client", new_callable=AsyncMock) as mock_get_llm, \
         patch("app.core.database.async_session_maker") as mock_session_maker, \
         patch("app.services.mission.manager.lifecycle.resolve_ip", new_callable=AsyncMock) as mock_resolve_ip:
        
        # Setup DB mocks details
        mock_session = AsyncMock()
        
        # async_session_maker() returns a context manager
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        
        # Make the callable return the context manager
        mock_session_maker.return_value = mock_session_ctx
        
        # session.begin() returns a transaction context manager
        mock_transaction_ctx = MagicMock()
        mock_transaction_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_transaction_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin = MagicMock(return_value=mock_transaction_ctx)
        
        mock_repo_instance = MockRepo.return_value
        mock_repo_instance.create = AsyncMock()
        mock_repo_instance.update = AsyncMock()
        
        # Setup Agents
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.execute_task = AsyncMock()
        
        mock_controller_instance = MockController.return_value
        mock_controller_instance.execute = AsyncMock()
        
        mock_scope_instance = MockScope.return_value
        mock_scope_instance.execute = AsyncMock()
        
        mock_voting_instance = MockVoting.return_value
        mock_voting_instance.validate_at_gate = AsyncMock()
        
        manager = MissionManager()
        
        yield {
            "manager": manager,
            "executor": mock_executor_instance,
            "controller": mock_controller_instance,
            "scope": mock_scope_instance,
            "voting": mock_voting_instance,
            "repo": mock_repo_instance,
            "resolve_ip": mock_resolve_ip
        }

@pytest.mark.asyncio
async def test_start_mission(mock_manager_context):
    manager = mock_manager_context["manager"]
    repo = mock_manager_context["repo"]
    resolve_ip = mock_manager_context["resolve_ip"]
    
    resolve_ip.return_value = {"city": "Test City", "country": "Test Country"}
    
    # Patch self.execution.run_mission_loop
    with patch.object(manager.execution, "run_mission_loop", new_callable=AsyncMock) as mock_loop:
        mission_id = await manager.start_mission("127.0.0.1", "test directive")
        
        assert mission_id in manager.active_missions
        repo.create.assert_called_once()
        mock_loop.assert_called_once()

@pytest.mark.asyncio
async def test_stop_mission(mock_manager_context):
    manager = mock_manager_context["manager"]
    
    # Patch execution loop to avoid background task
    with patch.object(manager.execution, "run_mission_loop", new_callable=AsyncMock):
        mission_id = await manager.start_mission("127.0.0.1", "test")
        
        assert await manager.stop_mission(mission_id) is True
        assert manager.active_missions[mission_id].is_stopped()
        
        assert await manager.stop_mission("invalid") is False

@pytest.mark.asyncio
async def test_run_mission_loop_success(mock_manager_context):
    manager = mock_manager_context["manager"]
    scope = mock_manager_context["scope"]
    controller = mock_manager_context["controller"]
    voting = mock_manager_context["voting"]
    executor = mock_manager_context["executor"]
    
    await manager._ensure_agents()
    
    mission = Mission("127.0.0.1", "test")
    manager.active_missions[mission.id] = mission
    
    # Mock Scope
    scope_result = MagicMock()
    scope_result.success = True
    scope_result.action.targets = ["127.0.0.1"]
    scope.execute.return_value = scope_result
    
    # Mock Plan
    plan_result = MagicMock()
    plan_result.success = True
    
    from app.services.ai.agents.mission_controller import MissionType
    plan_action = MissionPlan(
        mission_type=MissionType.CUSTOM,
        tasks=[
            Task(task_id="t1", description="d1", agent_type="agent1", phase=AssessmentPhase.DISCOVERY)
        ]
    )
    plan_result.action = plan_action
    controller.execute.return_value = plan_result
    
    # Mock Consensus
    vote = MagicMock()
    vote.status = "approved"
    vote.average_confidence = 0.9
    voting.validate_at_gate.return_value = vote
    
    # Invoke via execution manager
    await manager.execution.run_mission_loop(mission)
    
    scope.execute.assert_called_once()
    controller.execute.assert_called_once()
    voting.validate_at_gate.assert_called_once()
    executor.execute_task.assert_called_once()
    assert mission.status == "completed"

@pytest.mark.asyncio
async def test_adaptive_replanning(mock_manager_context):
    manager = mock_manager_context["manager"]
    controller = mock_manager_context["controller"]
    voting = mock_manager_context["voting"]
    executor = mock_manager_context["executor"]
    
    await manager._ensure_agents()
    mission = Mission("127.0.0.1", "test")
    
    executor.execute_task.side_effect = RuntimeError("Tool failed")
    
    task = Task(task_id="t1", description="d1", agent_type="agent1", phase=AssessmentPhase.DISCOVERY)
    from app.services.ai.agents.mission_controller import MissionType
    mission.plan = MissionPlan(mission_type=MissionType.CUSTOM, tasks=[task])
    
    context = AgentContext(session_id="1", target="1.1.1.1", mission="test")
    
    replan_result = MagicMock()
    replan_result.success = True

    from app.services.ai.agents.base import ActionRisk
    replan_action = SteeringAction(
        action_type="steering",
        confidence=0.9,
        risk_level=ActionRisk.LOW,
        reasoning="skip failing task",
        new_phase="discovery",
        skip_phases=["discovery"]
    )
    replan_result.action = replan_action
    controller.execute.return_value = replan_result
    
    vote = MagicMock()
    vote.status = "approved"
    voting.validate_at_gate.return_value = vote
    
    # Must call internal method on execution manager
    await manager.execution._execute_mission_tasks(mission, context)
    
    assert "discovery" in mission.skipped_phases

@pytest.mark.asyncio
async def test_get_mission(mock_manager_context):
    manager = mock_manager_context["manager"]
    # We need a mission in active_missions
    mission = Mission("127.0.0.1", "test")
    manager.active_missions[mission.id] = mission
    
    found_mission = await manager.get_mission(mission.id)
    assert found_mission is not None
    assert found_mission.id == mission.id
    
    assert await manager.get_mission("invalid") is None

def test_list_missions(mock_manager_context):
    manager = mock_manager_context["manager"]
    # Add manual missions
    m1 = Mission("1.1.1.1", "d1")
    m2 = Mission("2.2.2.2", "d2")
    manager.active_missions[m1.id] = m1
    manager.active_missions[m2.id] = m2
    
    missions = manager.list_missions()
    assert len(missions) == 2
    ids = [m["id"] for m in missions]
    assert m1.id in ids
    assert m2.id in ids

@pytest.mark.asyncio
async def test_pause_resume_mission(mock_manager_context):
    manager = mock_manager_context["manager"]
    repo = mock_manager_context["repo"]
    
    mission = Mission("1.1.1.1", "test")
    manager.active_missions[mission.id] = mission
    
    # Pause
    assert await manager.pause_mission(mission.id) is True
    assert mission.status == "paused"
    repo.update.assert_called()
    
    # Resume
    assert await manager.resume_mission(mission.id) is True
    assert mission.status == "running"
    
    assert await manager.pause_mission("invalid") is False
    assert await manager.resume_mission("invalid") is False

@pytest.mark.asyncio
async def test_steer_mission(mock_manager_context):
    manager = mock_manager_context["manager"]
    mission = Mission("1.1.1.1", "test")
    manager.active_missions[mission.id] = mission
    
    # Action: skip_phase
    result = await manager.steer_mission(mission.id, action="skip_phase", phase="discovery")
    assert "skipped" in result["message"]
    assert "discovery" in mission.skipped_phases
    
    # Action: prioritize_target
    result = await manager.steer_mission(mission.id, action="prioritize_target", target="192.168.1.5")
    assert "prioritized" in result["message"]
    # Verify it added a vector.
    # Note: MissionSteeringManager creates a new vector.
    # Check if vector count increased or check last log?
    # Mission log is easier:
    assert any("Prioritizing target: 192.168.1.5" in log for log in mission.logs)
    
    # Action: focus_vuln
    result = await manager.steer_mission(mission.id, action="focus_vuln", vulnerability="CVE-2024-1234")
    assert "Focusing" in result["message"]
    
    # Action: invalid mission
    with pytest.raises(ValueError):
        await manager.steer_mission("invalid", "skip_phase")
    
    # Action: invalid action
    # Note: SteeringManager might not raise ValueError for unknown action string if typed strictly, 
    # but let's assume it checks.
    # Looking at steering.py (Step 515), it has `if action == "skip_phase": ... else: raise ValueError`
    with pytest.raises(ValueError):
        await manager.steer_mission(mission.id, "invalid_action")
