"""Planner Graph — DAG-based mission planning with predicate/effect tracking.

Replaces ad-hoc LLM planning with a structured graph where:
- Nodes = mission states (phases + milestones with preconditions)
- Edges = causal dependencies (transition only when preconditions met)
- LLM only invoked when the graph has multiple valid next actions

This implements the CheckMate "Classical Planning+" concept — explicit
state representation with LLM-augmented dynamic updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from spectra_mission.framework_loader import (
    FrameworkSpec,
    get_framework,
)

logger = logging.getLogger(__name__)


class NodeType(StrEnum):
    PHASE = "phase"
    MILESTONE = "milestone"
    DECISION = "decision"  # Requires LLM to choose between paths
    ACTION = "action"  # Tool execution node


class NodeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class GraphNode:
    """A node in the planner graph."""

    id: str
    label: str
    node_type: NodeType
    preconditions: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A directed edge from one node to another."""

    source: str
    target: str
    label: str = ""
    condition: str = ""  # Predicate that must be true


class PlannerGraph:
    """DAG-based mission planner built from a framework spec.

    The graph is constructed from the framework's phases and milestones.
    State transitions happen when preconditions (predicates) are satisfied
    by facts discovered through the perceptor layer.
    """

    def __init__(self, framework_id: str | None = None):
        self.framework: FrameworkSpec = get_framework(framework_id)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self._facts: dict[str, Any] = {}  # Known facts (predicates)
        self._build_graph()

    # ── Graph construction ────────────────────────────────────────────

    def _build_graph(self) -> None:
        """Build the DAG from framework phases and milestones."""
        # Phase nodes
        ordered = sorted(self.framework.phases, key=lambda p: p.order)
        for i, phase in enumerate(ordered):
            preconds = []
            if i > 0:
                preconds.append(f"phase_{ordered[i - 1].id}_complete")

            node = GraphNode(
                id=f"phase_{phase.id}",
                label=phase.label,
                node_type=NodeType.PHASE,
                preconditions=preconds,
                metadata={"phase_id": phase.id, "description": phase.description},
            )
            self.nodes[node.id] = node

            # Edge from previous phase
            if i > 0:
                self.edges.append(
                    GraphEdge(
                        source=f"phase_{ordered[i - 1].id}",
                        target=f"phase_{phase.id}",
                        label=f"{ordered[i - 1].label} → {phase.label}",
                    )
                )

        # Milestone nodes (linked to their phases)
        for milestone in self.framework.milestones:
            node_id = f"milestone_{milestone.id}"
            self.nodes[node_id] = GraphNode(
                id=node_id,
                label=milestone.label,
                node_type=NodeType.MILESTONE,
                preconditions=[f"phase_{milestone.phase}_active"],
                metadata={"milestone_id": milestone.id, "phase": milestone.phase},
            )
            self.edges.append(
                GraphEdge(
                    source=f"phase_{milestone.phase}",
                    target=node_id,
                    label=milestone.label,
                )
            )

    # ── State management ──────────────────────────────────────────────

    def update_fact(self, predicate: str, value: Any = True) -> None:
        """Record a discovered fact (predicate becomes true)."""
        self._facts[predicate] = value
        logger.debug("Fact recorded: %s = %s", predicate, value)

        # Check if any blocked nodes can now transition
        for node in self.nodes.values():
            if node.status == NodeStatus.BLOCKED and self._preconditions_met(node):
                node.status = NodeStatus.PENDING

    def activate_phase(self, phase_id: str) -> None:
        """Mark a phase as active (in progress)."""
        node_id = f"phase_{phase_id}"
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.ACTIVE
            self.update_fact(f"phase_{phase_id}_active", True)

    def complete_phase(self, phase_id: str) -> str | None:
        """Mark a phase as complete. Returns the next phase ID if available."""
        node_id = f"phase_{phase_id}"
        if node_id not in self.nodes:
            return None

        self.nodes[node_id].status = NodeStatus.COMPLETED
        self.update_fact(f"phase_{phase_id}_complete", True)

        # Activate next phase if preconditions met
        for edge in self.edges:
            if edge.source == node_id:
                target = self.nodes.get(edge.target)
                if target and self._preconditions_met(target):
                    target.status = NodeStatus.ACTIVE
                    return target.metadata.get("phase_id")
        return None

    def complete_milestone(self, milestone_id: str) -> None:
        """Mark a milestone as completed."""
        node_id = f"milestone_{milestone_id}"
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.COMPLETED
            self.update_fact(f"milestone_{milestone_id}_complete", True)

    # ── Queries ───────────────────────────────────────────────────────

    def get_active_node(self) -> GraphNode | None:
        """Get the currently active phase node."""
        for node in self.nodes.values():
            if node.node_type == NodeType.PHASE and node.status == NodeStatus.ACTIVE:
                return node
        return None

    def get_pending_milestones(self, phase_id: str) -> list[GraphNode]:
        """Get pending milestones for a specific phase."""
        return [
            node
            for node in self.nodes.values()
            if node.node_type == NodeType.MILESTONE
            and node.metadata.get("phase") == phase_id
            and node.status in (NodeStatus.PENDING, NodeStatus.ACTIVE)
        ]

    def get_next_milestones(self) -> list[GraphNode]:
        """Get all milestones whose preconditions are met and are pending."""
        return [
            node
            for node in self.nodes.values()
            if node.node_type == NodeType.MILESTONE
            and node.status == NodeStatus.PENDING
            and self._preconditions_met(node)
        ]

    def needs_llm_decision(self) -> bool:
        """Check if the graph has multiple valid next actions requiring LLM choice."""
        pending = self.get_next_milestones()
        return len(pending) > 1

    def get_progress(self) -> dict[str, Any]:
        """Get overall graph progress."""
        phases = [n for n in self.nodes.values() if n.node_type == NodeType.PHASE]
        milestones = [n for n in self.nodes.values() if n.node_type == NodeType.MILESTONE]

        completed_phases = sum(1 for n in phases if n.status == NodeStatus.COMPLETED)
        completed_milestones = sum(1 for n in milestones if n.status == NodeStatus.COMPLETED)

        return {
            "phases_total": len(phases),
            "phases_completed": completed_phases,
            "milestones_total": len(milestones),
            "milestones_completed": completed_milestones,
            "active_phase": active.id if (active := self.get_active_node()) else None,
            "facts_count": len(self._facts),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph state for persistence."""
        return {
            "nodes": {
                nid: {
                    "id": node.id,
                    "label": node.label,
                    "type": node.node_type.value,
                    "status": node.status.value,
                    "metadata": node.metadata,
                }
                for nid, node in self.nodes.items()
            },
            "edges": [{"source": e.source, "target": e.target, "label": e.label} for e in self.edges],
            "facts": self._facts,
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _preconditions_met(self, node: GraphNode) -> bool:
        """Check if all preconditions for a node are satisfied."""
        return all(precond in self._facts for precond in node.preconditions)
