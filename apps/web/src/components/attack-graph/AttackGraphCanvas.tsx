import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, LoadingState } from "@/components/common/StateViews";
import { deriveAttackGraph, layoutWithElk } from "@/lib/attackGraph";
import type { MissionFindingSummary, MissionTaskTree } from "@/lib/types";
import { cn } from "@/lib/utils";

interface AttackGraphCanvasProps {
  taskTree: MissionTaskTree | undefined;
  findings: MissionFindingSummary[] | undefined;
  isLoading?: boolean;
  className?: string;
}

export function AttackGraphCanvas({ taskTree, findings, isLoading, className }: AttackGraphCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [layouting, setLayouting] = useState(false);

  const rawGraph = useMemo(() => deriveAttackGraph(taskTree, findings), [taskTree, findings]);

  useEffect(() => {
    if (!rawGraph.nodes.length) {
      setNodes([]);
      setEdges([]);
      return;
    }

    let cancelled = false;
    setLayouting(true);

    void layoutWithElk(rawGraph.nodes, rawGraph.edges).then((layoutNodes) => {
      if (cancelled) return;
      setNodes(layoutNodes);
      setEdges(rawGraph.edges);
      setLayouting(false);
    });

    return () => {
      cancelled = true;
    };
  }, [rawGraph, setNodes, setEdges]);

  const highlightedEdges = useMemo(() => {
    if (!selectedNodeId) return edges;
    return edges.map((edge) => {
      const onPath = edge.source === selectedNodeId || edge.target === selectedNodeId;
      return {
        ...edge,
        style: {
          ...edge.style,
          stroke: onPath ? "hsl(152 48% 42%)" : "hsl(215 9% 30%)",
          strokeWidth: onPath ? 2.5 : 1,
          opacity: onPath ? 1 : 0.35,
        },
      };
    });
  }, [edges, selectedNodeId]);

  const highlightedNodes = useMemo(() => {
    if (!selectedNodeId) return nodes;
    const connected = new Set<string>([selectedNodeId]);
    for (const edge of edges) {
      if (edge.source === selectedNodeId) connected.add(edge.target);
      if (edge.target === selectedNodeId) connected.add(edge.source);
    }
    return nodes.map((node) => ({
      ...node,
      style: {
        ...node.style,
        opacity: connected.has(node.id) ? 1 : 0.35,
        boxShadow: node.id === selectedNodeId ? "0 0 0 2px hsl(152 48% 42% / 0.5)" : undefined,
      },
    }));
  }, [nodes, edges, selectedNodeId]);

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNodeId((current) => (current === node.id ? null : node.id));
  }, []);

  if (isLoading || layouting) {
    return <LoadingState label="Building attack graph…" />;
  }

  if (!rawGraph.nodes.length) {
    return (
      <EmptyState
        title="No graph data"
        description="Select a mission with an active task tree, or wait for the agent to begin planning."
      />
    );
  }

  return (
    <div className={cn("h-[min(70vh,640px)] rounded-lg border border-border/60 bg-muted/10", className)}>
      <ReactFlow
        nodes={highlightedNodes}
        edges={highlightedEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        minZoom={0.2}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="hsl(222 10% 16%)" />
        <MiniMap
          nodeColor={(node) => {
            const kind = (node.data as { kind?: string }).kind;
            if (kind === "exploit" || kind === "finding") return "hsl(0 58% 48%)";
            if (kind === "entry_point") return "hsl(210 55% 52%)";
            return "hsl(215 9% 40%)";
          }}
          maskColor="hsl(222 18% 7% / 0.75)"
          className="!bg-card/80 !border-border/60"
        />
        <Controls className="!bg-card !border-border/60 [&>button]:!bg-card [&>button]:!border-border/60 [&>button]:!text-foreground" />
      </ReactFlow>
    </div>
  );
}
