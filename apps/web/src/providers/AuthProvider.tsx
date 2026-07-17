import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  cancelMfa as cancelMfaRequest,
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  verifyMfa as verifyMfaRequest,
  type AuthProfile,
} from "@/lib/api";

export type LoginResult =
  | { ok: true }
  | { ok: false; message: string }
  | { ok: "mfa"; mfaToken: string };

interface AuthContextValue {
  user: AuthProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isLoggingOut: boolean;
  error: ApiError | null;
  login: (username: string, password: string) => Promise<LoginResult>;
  verifyMfa: (mfaToken: string, code: string) => Promise<{ ok: true } | { ok: false; message: string }>;
  cancelMfa: (mfaToken: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function loadAuthenticatedProfile(): Promise<AuthProfile | null> {
  const result = await fetchCurrentUser();
  if (result.error) {
    if (result.error.status === 401 || result.error.status === 403) {
      return null;
    }
    throw result.error;
  }
  return result.data;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: loadAuthenticatedProfile,
    retry: false,
    staleTime: 60_000,
  });

  const login = useCallback(
    async (username: string, password: string): Promise<LoginResult> => {
      const result = await loginRequest(username, password);
      if (result.error) {
        const message =
          typeof result.error.detail === "string"
            ? result.error.detail
            : result.error.message || "Login failed";
        return { ok: false, message };
      }
      if (result.data?.mfa_required) {
        if (!result.data.mfa_token && !result.data.access_token) {
          return { ok: false, message: "MFA challenge could not be started. Try again." };
        }
        return { ok: "mfa", mfaToken: result.data.mfa_token ?? result.data.access_token };
      }
      try {
        const profile = await loadAuthenticatedProfile();
        if (!profile) {
          return { ok: false, message: "Signed in, but the session could not be restored. Try again." };
        }
        queryClient.setQueryData(["auth", "me"], profile);
      } catch (cause) {
        return {
          ok: false,
          message: cause instanceof Error ? cause.message : "Signed in, but the session could not be restored. Try again.",
        };
      }
      return { ok: true };
    },
    [queryClient],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      const result = await verifyMfaRequest(mfaToken, code);
      if (result.error) {
        const message =
          typeof result.error.detail === "string"
            ? result.error.detail
            : result.error.message || "Verification failed";
        return { ok: false as const, message };
      }
      try {
        const profile = await loadAuthenticatedProfile();
        if (!profile) {
          return { ok: false as const, message: "Verification succeeded, but the session could not be restored. Try again." };
        }
        queryClient.setQueryData(["auth", "me"], profile);
      } catch (cause) {
        return {
          ok: false as const,
          message:
            cause instanceof Error ? cause.message : "Verification succeeded, but the session could not be restored. Try again.",
        };
      }
      return { ok: true as const };
    },
    [queryClient],
  );

  const cancelMfa = useCallback(async (mfaToken: string) => {
    await cancelMfaRequest(mfaToken);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      // A failed network request must not leave sensitive operator data visible
      // after the user explicitly signs out. The server invalidates the cookie
      // when available; the client always clears its local session boundary.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "auth" });
      queryClient.setQueryData(["auth", "me"], null);
    }
  }, [queryClient]);

  const refreshSession = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: sessionQuery.data ?? null,
      isLoading: sessionQuery.isLoading,
      isAuthenticated: Boolean(sessionQuery.data),
      isLoggingOut: false,
      error: sessionQuery.error instanceof ApiError ? sessionQuery.error : null,
      login,
      verifyMfa,
      cancelMfa,
      logout,
      refreshSession,
    }),
    [cancelMfa, login, logout, refreshSession, sessionQuery.data, sessionQuery.error, sessionQuery.isLoading, verifyMfa],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
