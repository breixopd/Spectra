import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useMemo } from "react";

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
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading session...
      </div>
    );
  }

  return <RouterProvider router={router} context={context} />;
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
