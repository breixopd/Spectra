import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type { ToolListResponse } from "@/lib/types";

/** Tool detail matches API ToolDetailResponse. */
export interface ToolDetail {
  id: string;
  name: string;
  version: string;
  category: string;
  description: string;
  status: string;
  enabled: boolean;
  installed_version: string | null;
  error_message: string | null;
  timeout: number;
  icon: string;
  color: string;
  status_message: string | null;
  status_phase: string | null;
  last_updated: string | null;
  install_logs: string[];
  last_output: string | null;
}

export function useTools() {
  return useQuery({
    queryKey: queryKeys.tools.available,
    queryFn: async () => {
      const result = await api.get<ToolListResponse>("/api/v1/tools/available");
      return unwrapApiResult(result);
    },
  });
}

export function useTool(id: string) {
  return useQuery({
    queryKey: queryKeys.tools.detail(id),
    queryFn: async () => {
      const result = await api.get<ToolDetail>(`/api/v1/tools/${id}`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id),
  });
}

export interface InstallToolResponse {
  success: boolean;
  tool_id: string;
  status: string;
  message: string;
}

export interface TestExecutionResponse {
  tool_id: string;
  target: string;
  success: boolean;
  exit_code: number;
  duration_seconds: number;
  stdout: string;
  stderr: string;
  output_file: string | null;
  parsed_findings_count: number;
}

export function useInstallTool() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (toolId: string) => {
      const result = await api.post<InstallToolResponse>(`/api/v1/tools/${toolId}/install`);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      toast.success(data.message || "Install queued");
      void queryClient.invalidateQueries({ queryKey: queryKeys.tools.available });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tools.detail(data.tool_id) });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Install failed");
    },
  });
}

export function useTestTool() {
  return useMutation({
    mutationFn: async ({ toolId, target }: { toolId: string; target?: string }) => {
      const body = target ? { target } : {};
      const result = await api.post<TestExecutionResponse>(`/api/v1/tools/${toolId}/test`, body);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      if (data.success) {
        toast.success(`Test passed (${data.duration_seconds.toFixed(1)}s)`);
      } else {
        toast.error(`Test failed (exit ${data.exit_code})`);
      }
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Test failed");
    },
  });
}

export type { ToolListResponse };
