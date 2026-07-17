import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";

import { BrandMark } from "@/components/brand/BrandMark";
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
    <div className="relative min-h-screen bg-background lg:grid lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between border-r border-border/60 bg-card/30 p-10 lg:flex">
        <BrandMark size="lg" subtitle="Mission control" />
        <div className="space-y-6">
          <h1 className="max-w-md text-balance text-3xl font-semibold tracking-tight">
            Evidence-first autonomous assessments for security teams
          </h1>
          <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
            Coordinate specialist agents, sandboxed tool execution, and consensus-checked decisions — with proof
            bundles for every finding you report upstream.
          </p>
          <dl className="grid max-w-md grid-cols-2 gap-3 text-sm">
            <div className="rounded-md border border-border/60 bg-background/40 p-3">
              <dt className="text-2xs uppercase tracking-wider text-muted-foreground">Quality gates</dt>
              <dd className="mt-1 font-mono text-lg text-primary">8</dd>
            </div>
            <div className="rounded-md border border-border/60 bg-background/40 p-3">
              <dt className="text-2xs uppercase tracking-wider text-muted-foreground">Frameworks</dt>
              <dd className="mt-1 font-mono text-sm">PTES · OWASP · NIST</dd>
            </div>
          </dl>
        </div>
        <p className="text-2xs text-muted-foreground">Self-hosted · Your infrastructure · Your data</p>
      </div>

      <div className="relative flex items-center justify-center px-4 py-12">
        <div className="pointer-events-none absolute inset-0 bg-grid-fade opacity-40" aria-hidden />
        <div className="relative w-full max-w-md space-y-8">
          <div className="space-y-2 text-center lg:text-left">
            <div className="flex justify-center lg:hidden">
              <BrandMark size="md" />
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">
              {mfaToken ? "Two-factor verification" : "Sign in"}
            </h2>
            <p className="text-sm text-muted-foreground">
              {mfaToken
                ? "Enter the 6-digit code from your authenticator app."
                : "Access missions, findings, and live mission control."}
            </p>
          </div>

          <div className="rounded-xl border border-border/70 bg-card/80 p-8 shadow-surface backdrop-blur-sm">
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
                  {submitting ? "Verifying…" : "Verify and continue"}
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
          <p className="text-center text-2xs text-muted-foreground lg:text-left">
            Cookie session · CSRF-protected mutations
          </p>
        </div>
      </div>
    </div>
  );
}
