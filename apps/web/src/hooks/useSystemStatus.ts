import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type { SystemStatus } from "@/lib/types";

export function useSystemStatus(options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: queryKeys.system.status,
    queryFn: async () => {
      const result = await api.get<SystemStatus>("/api/v1/system/status");
      return unwrapApiResult(result);
    },
    refetchInterval: options?.refetchInterval ?? 30_000,
  });
}

export function useSystemStatusQuick() {
  return useQuery({
    queryKey: [...queryKeys.system.status, "quick"] as const,
    queryFn: async () => {
      const result = await api.get<{ status: string; message?: string }>("/api/v1/system/status/quick");
      return unwrapApiResult(result);
    },
    refetchInterval: 30_000,
  });
}
