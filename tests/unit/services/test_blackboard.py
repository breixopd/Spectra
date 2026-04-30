"""Mission blackboard contracts."""

import inspect

from app.services.ai.blackboard import MissionBlackboard


def test_cross_mission_findings_requires_user_id():
    sig = inspect.signature(MissionBlackboard.get_cross_mission_findings)
    assert "user_id" in sig.parameters
    assert sig.parameters["user_id"].default is inspect.Parameter.empty
