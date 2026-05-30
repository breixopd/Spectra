import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type {
  Mission,
  MissionArtifact,
  MissionFindingSummary,
  MissionProgress,
  MissionTaskTree,
  MissionsListParams,
  MissionsSummaryResponse,
  PaginatedResponse,
  StartMissionRequest,
  StatusResponse,
} from "@/lib/types";

export type { MissionsListParams };

function buildMissionsQuery(params: MissionsListParams = {}): string {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.per_page) search.set("per_page", String(params.per_page));
  if (params.status) search.set("status", params.status);
  if (params.target) search.set("target", params.target);
  if (params.search) search.set("search", params.search);
  if (params.sort_by) search.set("sort_by", params.sort_by);
  const query = search.toString();
  return query ? `/api/v1/missions?${query}` : "/api/v1/missions";
}

export function useMissions(params: MissionsListParams = {}) {
  return useQuery({
    queryKey: queryKeys.missions.list(params),
    queryFn: async () => {
      const result = await api.get<PaginatedResponse<Mission>>(buildMissionsQuery(params));
      return unwrapApiResult(result);
    },
  });
}

export function useMission(id: string) {
  return useQuery({
    queryKey: queryKeys.missions.detail(id),
    queryFn: async () => {
      const result = await api.get<Mission>(`/api/v1/missions/${id}`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id),
  });
}

export function useMissionProgress(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.missions.progress(id),
    queryFn: async () => {
      const result = await api.get<MissionProgress>(`/api/v1/missions/${id}/progress`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id) && enabled,
    retry: false,
    refetchInterval: 15_000,
  });
}

export function useMissionsSummary(params: { skip?: number; limit?: number } = {}) {
  const search = new URLSearchParams();
  if (params.skip !== undefined) search.set("skip", String(params.skip));
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  const query = search.toString();

  return useQuery({
    queryKey: queryKeys.missions.summary(params),
    queryFn: async () => {
      const url = query ? `/api/v1/missions/summary?${query}` : "/api/v1/missions/summary";
      const result = await api.get<MissionsSummaryResponse>(url);
      return unwrapApiResult(result);
    },
  });
}

export function useCreateMission() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (body: StartMissionRequest) => {
      const result = await api.post<Mission>("/api/v1/missions", body);
      return unwrapApiResult(result);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.missions.all });
    },
  });
}

export function useMissionTaskTree(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.missionsExtra.taskTree(id),
    queryFn: async () => {
      const result = await api.get<MissionTaskTree>(`/api/v1/missions/${id}/task-tree`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id) && enabled,
    retry: false,
  });
}

export function useMissionFindings(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.missionsExtra.findings(id),
    queryFn: async () => {
      const result = await api.get<MissionFindingSummary[]>(`/api/v1/missions/${id}/findings`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id) && enabled,
  });
}

export function useMissionArtifacts(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.missionsExtra.artifacts(id),
    queryFn: async () => {
      const result = await api.get<MissionArtifact[]>(`/api/v1/missions/${id}/artifacts`);
      return unwrapApiResult(result);
    },
    enabled: Boolean(id) && enabled,
    retry: false,
  });
}

function useMissionLifecycleMutation(
  action: "pause" | "resume" | "stop",
  optimisticStatus: string,
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (missionId: string) => {
      const result = await api.post<StatusResponse>(`/api/v1/missions/${missionId}/${action}`);
      return unwrapApiResult(result);
    },
    onMutate: async (missionId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.missions.detail(missionId) });
      const previous = queryClient.getQueryData<Mission>(queryKeys.missions.detail(missionId));
      if (previous) {
        queryClient.setQueryData<Mission>(queryKeys.missions.detail(missionId), {
          ...previous,
          status: optimisticStatus,
        });
      }
      return { previous, missionId };
    },
    onError: (_err, missionId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.missions.detail(missionId), context.previous);
      }
    },
    onSettled: (_data, _err, missionId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.missions.detail(missionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.missions.all });
    },
  });
}

export function usePauseMission() {
  return useMissionLifecycleMutation("pause", "paused");
}

export function useResumeMission() {
  return useMissionLifecycleMutation("resume", "running");
}

export function useStopMission() {
  return useMissionLifecycleMutation("stop", "stopping");
}
