import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type { ApiKeyCreateResponse, ApiKeySummary } from "@/lib/types";

export function useApiKeys() {
  return useQuery({
    queryKey: queryKeys.user.apiKeys,
    queryFn: async () => {
      const result = await api.get<ApiKeySummary[]>("/api/v1/auth/api-keys");
      return unwrapApiResult(result);
    },
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (name: string) => {
      const result = await api.post<ApiKeyCreateResponse>("/api/v1/auth/api-keys", { name });
      return unwrapApiResult(result);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.user.apiKeys });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Failed to create API key");
    },
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (keyId: string) => {
      const result = await api.delete<{ detail: string }>(`/api/v1/auth/api-keys/${keyId}`);
      return unwrapApiResult(result);
    },
    onSuccess: () => {
      toast.success("API key revoked");
      void queryClient.invalidateQueries({ queryKey: queryKeys.user.apiKeys });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Failed to revoke key");
    },
  });
}
