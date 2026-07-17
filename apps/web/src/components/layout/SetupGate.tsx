import { useEffect, useState } from "react";

import { api } from "@/lib/api";

/**
 * Redirects to Jinja setup wizard when no admin exists yet.
 * Setup stays server-rendered; product SPA starts after first user is created.
 */
export function SetupGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await api.get<{ is_setup: boolean }>("/api/v1/auth/setup/status");
      if (cancelled) {
        return;
      }
      if (!result.error && result.data && !result.data.is_setup) {
        window.location.replace("/setup");
        return;
      }
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background">
        <div className="h-8 w-8 animate-pulse rounded-lg bg-primary/20" />
        <p className="text-sm text-muted-foreground">Checking platform status…</p>
      </div>
    );
  }

  return <>{children}</>;
}
