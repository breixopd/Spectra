"""
Mission State Machine.

Formalizes mission state transitions with explicit validation.
Ensures only valid state changes occur and provides audit trail.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.enums import MissionStatus
from app.core.events import EventType, events
from app.core.exceptions import MissionStateError
from app.core.telemetry import telemetry as _telemetry

# Backward-compatible alias — new code should use MissionStatus directly.
MissionState = MissionStatus


# Valid state transitions
VALID_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.CREATED: {
        MissionStatus.INITIALIZING,
        MissionStatus.CANCELLED,
    },
    MissionStatus.INITIALIZING: {
        MissionStatus.SCOPING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.SCOPING: {
        MissionStatus.PLANNING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.PLANNING: {
        MissionStatus.EXECUTING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.EXECUTING: {
        MissionStatus.EXPLOITING,
        MissionStatus.REPORTING,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.PAUSED,
        MissionStatus.SCANNING,
        MissionStatus.ANALYZING,
    },
    MissionStatus.SCANNING: {
        MissionStatus.EXECUTING,
        MissionStatus.ANALYZING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.ANALYZING: {
        MissionStatus.EXECUTING,
        MissionStatus.EXPLOITING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.EXPLOITING: {
        MissionStatus.REPORTING,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.PAUSED,
    },
    MissionStatus.REPORTING: {
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.PAUSED: {
        MissionStatus.EXECUTING,
        MissionStatus.EXPLOITING,
        MissionStatus.CANCELLED,
    },
    MissionStatus.RUNNING: {
        MissionStatus.EXECUTING,
        MissionStatus.SCANNING,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.STOPPING,
        MissionStatus.PAUSED,
    },
    MissionStatus.STOPPING: {
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
    },
    # Terminal states - no valid transitions out
    MissionStatus.COMPLETED: set(),
    MissionStatus.FAILED: set(),
    MissionStatus.CANCELLED: set(),
}


@dataclass
class StateTransition:
    """Records a state transition."""

    from_state: MissionStatus
    to_state: MissionStatus
    timestamp: datetime = field(default_factory=datetime.now)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "metadata": self.metadata,
        }


class MissionStateMachine:
    """
    State machine for mission lifecycle management.

    Ensures valid state transitions and maintains audit trail.

    Usage:
        fsm = MissionStateMachine("mission-123")
        fsm.transition_to(MissionState.INITIALIZING)
        fsm.transition_to(MissionState.SCOPING)
        ...
    """

    def __init__(
        self, mission_id: str, initial_state: MissionStatus = MissionStatus.CREATED
    ):
        self.mission_id = mission_id
        self._state = initial_state
        self._history: list[StateTransition] = []
        self._created_at = datetime.now()

    @property
    def state(self) -> MissionState:
        """Get current state."""
        return self._state

    @property
    def is_terminal(self) -> bool:
        """Check if in a terminal state."""
        return self._state in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }

    @property
    def is_active(self) -> bool:
        """Check if mission is actively running."""
        return self._state in {
            MissionStatus.INITIALIZING,
            MissionStatus.SCOPING,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.SCANNING,
            MissionStatus.ANALYZING,
            MissionStatus.EXPLOITING,
            MissionStatus.REPORTING,
            MissionStatus.RUNNING,
        }

    def can_transition_to(self, new_state: MissionStatus) -> bool:
        """Check if transition to new_state is valid."""
        valid_targets = VALID_TRANSITIONS.get(self._state, set())
        return new_state in valid_targets

    def get_valid_transitions(self) -> set[MissionStatus]:
        """Get all valid state transitions from current state."""
        return VALID_TRANSITIONS.get(self._state, set()).copy()

    def transition_to(
        self,
        new_state: MissionStatus,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateTransition:
        """
        Transition to a new state.

        Args:
            new_state: Target state
            reason: Optional reason for transition
            metadata: Optional additional data

        Returns:
            StateTransition record

        Raises:
            MissionStateError: If transition is invalid
        """
        if not self.can_transition_to(new_state):
            raise MissionStateError(
                self.mission_id,
                self._state.value,
                new_state.value,
            )

        transition = StateTransition(
            from_state=self._state,
            to_state=new_state,
            reason=reason,
            metadata=metadata or {},
        )

        old_state = self._state
        self._state = new_state
        self._history.append(transition)

        # Emit event
        events.emit_sync(
            EventType.MISSION_PHASE_CHANGED,
            source="state_machine",
            mission_id=self.mission_id,
            from_state=old_state.value,
            to_state=new_state.value,
            reason=reason,
        )

        # Record telemetry
        _telemetry.increment_counter(
            "mission_events_total",
            1,
            {"event": f"{old_state.value}_to_{new_state.value}", "phase": new_state.value},
        )

        return transition

    def force_transition(
        self,
        new_state: MissionStatus,
        reason: str = "Forced transition",
    ) -> StateTransition:
        """
        Force a transition regardless of validity.

        Should only be used for error recovery or admin actions.
        """
        transition = StateTransition(
            from_state=self._state,
            to_state=new_state,
            reason=f"[FORCED] {reason}",
            metadata={"forced": True},
        )

        self._state = new_state
        self._history.append(transition)

        return transition

    def get_history(self) -> list[dict[str, Any]]:
        """Get state transition history."""
        return [t.to_dict() for t in self._history]

    def get_duration(self) -> float:
        """Get total duration in seconds."""
        return (datetime.now() - self._created_at).total_seconds()

    def get_time_in_state(self, state: MissionStatus) -> float:
        """Get total time spent in a specific state."""
        total = 0.0

        for i, transition in enumerate(self._history):
            if transition.to_state == state:
                # Find when we left this state
                if i + 1 < len(self._history):
                    next_transition = self._history[i + 1]
                    duration = (
                        next_transition.timestamp - transition.timestamp
                    ).total_seconds()
                else:
                    # Still in this state
                    duration = (datetime.now() - transition.timestamp).total_seconds()
                total += duration

        return total

    def to_dict(self) -> dict[str, Any]:
        """Serialize state machine to dictionary."""
        return {
            "mission_id": self.mission_id,
            "current_state": self._state.value,
            "is_terminal": self.is_terminal,
            "is_active": self.is_active,
            "created_at": self._created_at.isoformat(),
            "duration_seconds": self.get_duration(),
            "valid_transitions": [s.value for s in self.get_valid_transitions()],
            "history": self.get_history(),
        }


# --- Phase Mapping ---

# Map old string phases to new states
PHASE_TO_STATE: dict[str, MissionState] = {
    "created": MissionState.CREATED,
    "running": MissionState.EXECUTING,
    "scope": MissionState.SCOPING,
    "discovery": MissionState.EXECUTING,
    "enumeration": MissionState.EXECUTING,
    "vulnerability": MissionState.EXECUTING,
    "exploitation": MissionState.EXPLOITING,
    "post_exploitation": MissionState.EXPLOITING,
    "reporting": MissionState.REPORTING,
    "complete": MissionState.COMPLETED,
    "completed": MissionState.COMPLETED,
    "failed": MissionState.FAILED,
    "cancelled": MissionState.CANCELLED,
    "stopping": MissionState.CANCELLED,
}


def phase_to_state(phase: str) -> MissionState:
    """Convert assessment phase string to MissionState."""
    return PHASE_TO_STATE.get(phase.lower(), MissionState.EXECUTING)


__all__ = [
    "MissionState",
    "MissionStateMachine",
    "StateTransition",
    "VALID_TRANSITIONS",
    "phase_to_state",
]
