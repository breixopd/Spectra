import type { Edge, Node } from "@xyflow/react";

import type { AttackGraphNodeKind, MissionFindingSummary, MissionTaskTree, TaskTreeNode } from "@/lib/types";

export interface AttackGraphData {
  nodes: Node[];
  edges: Edge[];
}

function inferNodeKind(node: TaskTreeNode): AttackGraphNodeKind {
  const technique = node.technique.toLowerCase();
  if (node.findings.length > 0) return "finding";
  if (technique.includes("credential") || technique.includes("auth")) return "credential";
  if (technique.startsWith("exploit") || technique.includes("/rce") || technique.includes("/sqli")) return "exploit";
  if (technique.startsWith("privesc") || technique.includes("pivot") || technique.includes("lateral")) return "pivot";
  if (technique.includes("service") || technique.includes("port") || technique.includes("banner")) return "service";
  if (technique.startsWith("recon") || technique === "mission" || technique.includes("scan")) return "entry_point";
  return "task";
}

function nodeStyle(kind: AttackGraphNodeKind): { borderColor: string; background: string } {
  switch (kind) {
    case "entry_point":
      return { borderColor: "hsl(210 55% 52%)", background: "hsl(210 55% 52% / 0.12)" };
    case "service":
      return { borderColor: "hsl(215 9% 52%)", background: "hsl(222 12% 16%)" };
    case "credential":
      return { borderColor: "hsl(36 88% 48%)", background: "hsl(36 88% 48% / 0.1)" };
    case "pivot":
      return { borderColor: "hsl(280 45% 55%)", background: "hsl(280 45% 55% / 0.1)" };
    case "exploit":
      return { borderColor: "hsl(0 58% 48%)", background: "hsl(0 58% 48% / 0.12)" };
    case "finding":
      return { borderColor: "hsl(0 58% 48%)", background: "hsl(0 58% 48% / 0.18)" };
    default:
      return { borderColor: "hsl(152 48% 42%)", background: "hsl(152 48% 42% / 0.08)" };
  }
}

export function deriveAttackGraph(
  taskTree: MissionTaskTree | undefined,
  findings: MissionFindingSummary[] | undefined,
): AttackGraphData {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const findingById = new Map((findings ?? []).map((f) => [f.id, f]));

  if (!taskTree?.nodes || Object.keys(taskTree.nodes).length <= 1) {
    return { nodes, edges };
  }

  for (const [nodeId, node] of Object.entries(taskTree.nodes)) {
    if (nodeId === "root") continue;

    const kind = inferNodeKind(node);
    const style = nodeStyle(kind);
    const isVerifiedFinding =
      kind === "finding" ||
      node.findings.some((fid) => {
        const f = findingById.get(fid);
        return f?.status === "verified" || f?.status === "exploited";
      });

    nodes.push({
      id: nodeId,
      type: "default",
      position: { x: 0, y: 0 },
      data: {
        label: node.name,
        kind,
        status: node.status,
        technique: node.technique,
        tool: node.tool_used,
      },
      style: {
        border: `1px solid ${style.borderColor}`,
        background: style.background,
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: 11,
        color: "hsl(210 18% 94%)",
        minWidth: 120,
        borderStyle: isVerifiedFinding ? "solid" : kind === "task" ? "dashed" : "solid",
      },
    });

    if (node.parent_id && node.parent_id !== "root") {
      edges.push({
        id: `${node.parent_id}->${nodeId}`,
        source: node.parent_id,
        target: nodeId,
        animated: node.status === "active",
        style: {
          stroke: isVerifiedFinding ? "hsl(0 58% 48%)" : "hsl(215 9% 40%)",
          strokeWidth: isVerifiedFinding ? 2 : 1,
        },
      });
    }
  }

  return { nodes, edges };
}

export async function layoutWithElk(nodes: Node[], edges: Edge[]): Promise<Node[]> {
  const ELK = (await import("elkjs/lib/elk.bundled.js")).default;
  const elk = new ELK();

  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.spacing.nodeNode": "48",
      "elk.layered.spacing.nodeNodeBetweenLayers": "64",
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: 160,
      height: 48,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
  };

  const layout = await elk.layout(graph);
  const positions = new Map<string, { x: number; y: number }>();
  for (const child of layout.children ?? []) {
    positions.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }

  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? node.position,
  }));
}
