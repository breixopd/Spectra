import { Shield } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/providers/AuthProvider";

export function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await login(username, password);
    if (!result.ok) {
      setError(result.message);
    }
    setSubmitting(false);
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, hsl(152 48% 42% / 0.15), transparent), radial-gradient(ellipse 60% 40% at 100% 100%, hsl(210 55% 52% / 0.08), transparent)",
        }}
      />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-border/60 bg-card shadow-surface">
            <Shield className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Spectra</p>
            <h1 className="text-2xl font-semibold tracking-tight">Sign in to Mission Control</h1>
            <p className="text-sm text-muted-foreground">
              Autonomous penetration testing — evidence-first, operator-grade.
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-border/60 bg-card/80 p-8 shadow-surface backdrop-blur-sm">
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          <p className="mt-6 text-center text-2xs text-muted-foreground">
            Cookie session · CSRF-protected mutations
          </p>
        </div>
      </div>
    </div>
  );
}
