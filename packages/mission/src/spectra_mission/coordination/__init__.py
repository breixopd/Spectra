"""Coordination layer — validates, decomposes, and orchestrates pentest actions.

ScopeEnforcer     — validates actions against RoE + framework policy
TaskDecomposer    — breaks plan tasks into single-tool micro-tasks
Orchestrator      — manages concurrent execution, ordering, retries
"""

from spectra_mission.coordination.orchestrator import Orchestrator
from spectra_mission.coordination.scope_enforcer import ScopeEnforcer
from spectra_mission.coordination.task_decomposer import TaskDecomposer

__all__ = ["Orchestrator", "ScopeEnforcer", "TaskDecomposer"]
