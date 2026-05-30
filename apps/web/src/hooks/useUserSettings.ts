import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { unwrapApiResult } from "@/lib/api-helpers";
import { queryKeys } from "@/lib/queryKeys";
import type { UserSettings, UserSettingsUpdate } from "@/lib/types";

export function useUserSettings() {
  return useQuery({
    queryKey: queryKeys.user.settings,
    queryFn: async () => {
      const result = await api.get<UserSettings>("/api/v1/user/settings");
      return unwrapApiResult(result);
    },
  });
}

export function useUpdateUserSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (body: UserSettingsUpdate) => {
      const result = await api.put<UserSettings>("/api/v1/user/settings", body);
      return unwrapApiResult(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.user.settings, data);
      toast.success("Settings saved");
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Failed to save settings");
    },
  });
}
