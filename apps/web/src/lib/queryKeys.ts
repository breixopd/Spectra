import type { FindingsListParams, MissionsListParams } from "./types";

export const queryKeys = {
  missions: {
    all: ["missions"] as const,
    list: (params?: MissionsListParams) => ["missions", "list", params] as const,
    detail: (id: string) => ["missions", "detail", id] as const,
    progress: (id: string) => ["missions", "progress", id] as const,
    summary: (params?: { skip?: number; limit?: number }) => ["missions", "summary", params] as const,
  },
  findings: {
    all: ["findings"] as const,
    list: (params?: FindingsListParams) => ["findings", "list", params] as const,
    detail: (id: string) => ["findings", "detail", id] as const,
  },
  system: {
    status: ["system", "status"] as const,
  },
  tools: {
    available: ["tools", "available"] as const,
    detail: (id: string) => ["tools", "detail", id] as const,
  },
  user: {
    settings: ["user", "settings"] as const,
    apiKeys: ["user", "api-keys"] as const,
  },
  missionsExtra: {
    taskTree: (id: string) => ["missions", "task-tree", id] as const,
    findings: (id: string) => ["missions", "findings", id] as const,
    artifacts: (id: string) => ["missions", "artifacts", id] as const,
  },
} as const;
