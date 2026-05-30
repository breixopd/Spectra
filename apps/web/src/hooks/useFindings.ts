import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type {
  Finding,
  FindingDetail,
  FindingUpdateRequest,
  FindingsListParams,
  PaginatedResponse,
} from "@/lib/types";

export type { FindingsListParams };

function buildFindingsQuery(params: FindingsListParams = {}): string {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.per_page) search.set("per_page", String(params.per_page));
  if (params.severity) search.set("severity", params.severity);
  if (params.status) search.set("status", params.status);
  if (params.proof_status) search.set("proof_status", params.proof_status);
  const query = search.toString();
  return query ? `/api/v1/findings?${query}` : "/api/v1/findings";
}

export function useFindings(params: FindingsListParams = {}) {
  return useQuery({
    queryKey: queryKeys.findings.list(params),
    queryFn: async () => {
      const result = await api.get<PaginatedResponse<FindingDetail>>(buildFindingsQuery(params));
      return unwrapApiResult(result);
    },
  });
}

export function useFinding(id: string) {
  return useQuery({
    queryKey: queryKeys.findings.detail(id),
    queryFn: async () => {
      const result = await api.get<FindingDetail>(`/api/v1/findings/${id}`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id),
  });
}

export function useFindingDetails(ids: string[], enabled = true) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.findings.detail(id),
      queryFn: async () => {
        const result = await api.get<FindingDetail>(`/api/v1/findings/${id}`);
        return unwrapApiResult(result);
      },
      enabled: enabled && Boolean(id),
      staleTime: 60_000,
    })),
  });
}

export function useUpdateFinding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, body }: { id: string; body: FindingUpdateRequest }) => {
      const result = await api.patch<FindingDetail>(`/api/v1/findings/${id}`, body);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.findings.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.findings.all });
    },
  });
}

export function useRetestFinding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.post<FindingDetail>(`/api/v1/findings/${id}/retest`);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.findings.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.findings.all });
    },
  });
}

export function useVerifyFinding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.post<FindingDetail>(`/api/v1/findings/${id}/verify`);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.findings.detail(data.id), data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.findings.all });
    },
  });
}

export type { Finding, FindingDetail };
