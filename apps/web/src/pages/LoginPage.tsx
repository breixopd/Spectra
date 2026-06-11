import { KeyRound, Shield } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/providers/AuthProvider";

export function LoginPage() {
  const { login, verifyMfa, cancelMfa } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await login(username, password);
    if (result.ok === "mfa") {
      setMfaToken(result.mfaToken);
    } else if (!result.ok) {
      setError(result.message);
    }
    setSubmitting(false);
  }

  async function onSubmitMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mfaToken) {
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await verifyMfa(mfaToken, mfaCode.trim());
    if (!result.ok) {
      setError(result.message);
    }
    setSubmitting(false);
  }

  async function onCancelMfa() {
    if (mfaToken) {
      void cancelMfa(mfaToken);
    }
    setMfaToken(null);
    setMfaCode("");
    setError(null);
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
            <h1 className="text-2xl font-semibold tracking-tight">
              {mfaToken ? "Two-factor verification" : "Sign in to Mission Control"}
            </h1>
            <p className="text-sm text-muted-foreground">
              {mfaToken
                ? "Enter the 6-digit code from your authenticator app."
                : "Autonomous pentesting with evidence for every finding."}
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-border/60 bg-card/80 p-8 shadow-surface backdrop-blur-sm">
          {mfaToken ? (
            <form className="space-y-4" onSubmit={onSubmitMfa}>
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Authentication code</Label>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="mfa-code"
                    className="pl-9 font-mono text-base tracking-[0.3em]"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    placeholder="000000"
                    value={mfaCode}
                    onChange={(event) => setMfaCode(event.target.value.replace(/\D/g, ""))}
                    autoFocus
                    required
                  />
                </div>
              </div>
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
              <Button type="submit" className="w-full" disabled={submitting || mfaCode.length !== 6}>
                {submitting ? "Verifying…" : "Verify and sign in"}
              </Button>
              <Button type="button" variant="ghost" className="w-full" onClick={() => void onCancelMfa()}>
                Back to sign in
              </Button>
            </form>
          ) : (
            <>
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
              <div className="mt-6 flex items-center justify-between text-xs text-muted-foreground">
                <a href="/forgot-password" className="transition-colors hover:text-foreground">
                  Forgot password?
                </a>
                <a href="/register" className="transition-colors hover:text-foreground">
                  Create account
                </a>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
