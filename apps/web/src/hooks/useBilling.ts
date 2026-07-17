import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface BillingPlan {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  features: Record<string, boolean> | null;
  max_concurrent_missions: number;
  max_missions_per_month: number | null;
  max_targets: number | null;
  max_storage_mb: number;
  checkout_available: boolean;
  checkout_provider: string;
}

export interface BillingUsage {
  storage_used_mb: number;
  max_storage_mb: number;
  storage_pct: number;
  plan_name: string | null;
}

export function useBillingPlans() {
  return useQuery({
    queryKey: ["billing", "plans"],
    queryFn: async () => {
      const result = await api.get<BillingPlan[]>("/api/v1/billing/plans");
      if (result.error) {
        throw result.error;
      }
      return result.data ?? [];
    },
  });
}

export function useBillingUsage() {
  return useQuery({
    queryKey: ["billing", "usage"],
    queryFn: async () => {
      const result = await api.get<BillingUsage>("/api/v1/billing/usage");
      if (result.error) {
        throw result.error;
      }
      return result.data;
    },
  });
}

export function useBillingCheckout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (planId: string) => {
      const result = await api.post<{ checkout_url: string }>(`/api/v1/billing/checkout?plan_id=${encodeURIComponent(planId)}`);
      if (result.error) {
        throw result.error;
      }
      return result.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["billing"] });
      void queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

export function useBillingPortal() {
  return useMutation({
    mutationFn: async () => {
      const result = await api.get<{ portal_url: string }>("/api/v1/billing/portal");
      if (result.error) {
        throw result.error;
      }
      return result.data;
    },
  });
}
