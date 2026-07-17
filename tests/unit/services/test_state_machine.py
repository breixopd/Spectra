"""Extended tests for MissionStateMachine (app/core/state_machine.py).

Supplements the basic tests in test_core_infrastructure.py with:
- Telemetry recording on transition
- Full lifecycle walk-through
- StateTransition serialisation
- Edge cases for get_time_in_state and to_dict
"""

from unittest.mock import patch

import pytest

from spectra_common.errors import MissionStateError
from spectra_domain.enums import MissionStatus
from spectra_mission.core.state_machine import (
    VALID_TRANSITIONS,
    MissionStateMachine,
    StateTransition,
)


class TestStateTransition:
    """Tests for the StateTransition dataclass."""

    def test_to_dict_fields(self):
        t = StateTransition(
            from_state=MissionStatus.CREATED,
            to_state=MissionStatus.INITIALIZING,
            reason="start",
            metadata={"key": "val"},
        )
        d = t.to_dict()
        assert d["from_state"] == "created"
        assert d["to_state"] == "initializing"
        assert d["reason"] == "start"
        assert d["metadata"] == {"key": "val"}
        assert "timestamp" in d

    def test_default_metadata_is_empty(self):
        t = StateTransition(
            from_state=MissionStatus.CREATED,
            to_state=MissionStatus.INITIALIZING,
        )
        assert t.metadata == {}
        assert t.reason is None


class TestTelemetryOnTransition:
    """Verify that transitions emit telemetry counters."""

    def test_transition_increments_counter(self):
        with (
            patch("spectra_mission.core.state_machine._telemetry") as mock_tel,
            patch("spectra_mission.core.state_machine.events"),
        ):
            fsm = MissionStateMachine("t-1")
            fsm.transition_to(MissionStatus.INITIALIZING)

        mock_tel.increment_counter.assert_called_once_with(
            "mission_events_total",
            1,
            {"event": "created_to_initializing", "phase": "initializing"},
        )

    def test_multiple_transitions_emit_multiple_counters(self):
        with (
            patch("spectra_mission.core.state_machine._telemetry") as mock_tel,
            patch("spectra_mission.core.state_machine.events"),
        ):
            fsm = MissionStateMachine("t-2")
            fsm.transition_to(MissionStatus.INITIALIZING)
            fsm.transition_to(MissionStatus.SCOPING)

        assert mock_tel.increment_counter.call_count == 2


class TestFullLifecycle:
    """Walk through the happy-path lifecycle."""

    def test_created_to_completed(self):
        with patch("spectra_mission.core.state_machine._telemetry"), patch("spectra_mission.core.state_machine.events"):
            fsm = MissionStateMachine("lifecycle-1")
            for state in [
                MissionStatus.INITIALIZING,
                MissionStatus.SCOPING,
                MissionStatus.PLANNING,
                MissionStatus.EXECUTING,
                MissionStatus.REPORTING,
                MissionStatus.COMPLETED,
            ]:
                fsm.transition_to(state)

        assert fsm.state == MissionStatus.COMPLETED
        assert fsm.is_terminal
        assert not fsm.is_active
        assert len(fsm.get_history()) == 6

    def test_no_valid_transitions_from_terminal(self):
        with patch("spectra_mission.core.state_machine._telemetry"), patch("spectra_mission.core.state_machine.events"):
            fsm = MissionStateMachine("term-1")
            fsm.force_transition(MissionStatus.FAILED)

        assert fsm.get_valid_transitions() == set()
        with pytest.raises(MissionStateError):
            with (
                patch("spectra_mission.core.state_machine._telemetry"),
                patch("spectra_mission.core.state_machine.events"),
            ):
                fsm.transition_to(MissionStatus.EXECUTING)


class TestValidTransitionsMap:
    """Validate structural invariants of the transition map."""

    def test_all_statuses_present(self):
        for status in MissionStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"

    def test_terminal_states_empty(self):
        for terminal in (MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED):
            assert VALID_TRANSITIONS[terminal] == set()

    def test_cancelled_reachable_from_most_states(self):
        for status, targets in VALID_TRANSITIONS.items():
            if status in (MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED):
                continue
            assert MissionStatus.CANCELLED in targets or MissionStatus.FAILED in targets, (
                f"{status} has no path to CANCELLED or FAILED"
            )


class TestStateMachineEdgeCases:
    """Edge-case scenarios."""

    def test_custom_initial_state(self):
        fsm = MissionStateMachine("e-1", initial_state=MissionStatus.PAUSED)
        assert fsm.state == MissionStatus.PAUSED

    def test_get_duration_positive(self):
        fsm = MissionStateMachine("e-2")
        assert fsm.get_duration() >= 0

    def test_to_dict_structure(self):
        with patch("spectra_mission.core.state_machine._telemetry"), patch("spectra_mission.core.state_machine.events"):
            fsm = MissionStateMachine("e-3")
            fsm.transition_to(MissionStatus.INITIALIZING)

        d = fsm.to_dict()
        assert d["mission_id"] == "e-3"
        assert d["current_state"] == "initializing"
        assert d["is_active"] is True
        assert d["is_terminal"] is False
        assert isinstance(d["valid_transitions"], list)
        assert isinstance(d["history"], list)

    def test_force_transition_records_forced_flag(self):
        fsm = MissionStateMachine("e-4")
        t = fsm.force_transition(MissionStatus.FAILED, "admin action")
        assert t.metadata.get("forced") is True
        assert "[FORCED]" in (t.reason or "")

    def test_transition_with_reason_and_metadata(self):
        with patch("spectra_mission.core.state_machine._telemetry"), patch("spectra_mission.core.state_machine.events"):
            fsm = MissionStateMachine("e-5")
            t = fsm.transition_to(
                MissionStatus.INITIALIZING,
                reason="auto-start",
                metadata={"trigger": "api"},
            )
        assert t.reason == "auto-start"
        assert t.metadata == {"trigger": "api"}
