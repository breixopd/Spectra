import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useMemo } from "react";

import { BrandMark } from "@/components/brand/BrandMark";
import { SetupGate } from "@/components/layout/SetupGate";
import { Toaster } from "@/components/ui/sonner";
import { queryClient } from "@/lib/queryClient";
import { AuthProvider, useAuth } from "@/providers/AuthProvider";
import { router } from "@/router";

function RouterWithAuth() {
  const auth = useAuth();
  const context = useMemo(
    () => ({
      auth: {
        isAuthenticated: auth.isAuthenticated,
        isLoading: auth.isLoading,
      },
    }),
    [auth.isAuthenticated, auth.isLoading],
  );

  if (auth.isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background">
        <BrandMark size="lg" subtitle="Loading session" />
        <p className="text-sm text-muted-foreground">Restoring your workspace…</p>
      </div>
    );
  }

  return (
    <SetupGate>
      <RouterProvider router={router} context={context} />
    </SetupGate>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterWithAuth />
        <Toaster richColors closeButton />
      </AuthProvider>
    </QueryClientProvider>
  );
}
