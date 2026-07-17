import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Retrying auth, validation, and permission failures only adds latency and
      // duplicate traffic. A single retry is useful for transient transport/5xx.
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
      },
      refetchOnWindowFocus: true,
    },
  },
});
