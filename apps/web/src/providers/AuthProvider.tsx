import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, fetchCurrentUser, login as loginRequest, logout as logoutRequest, type AuthProfile } from "@/lib/api";
import { router } from "@/router";

interface AuthContextValue {
  user: AuthProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isLoggingOut: boolean;
  error: ApiError | null;
  login: (username: string, password: string) => Promise<{ ok: true } | { ok: false; message: string }>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const sessionQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const result = await fetchCurrentUser();
      if (result.error) {
        if (result.error.status === 401 || result.error.status === 403) {
          return null;
        }
        throw result.error;
      }
      return result.data;
    },
    retry: false,
    staleTime: 60_000,
  });

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await loginRequest(username, password);
      if (result.error) {
        const message =
          typeof result.error.detail === "string"
            ? result.error.detail
            : result.error.message || "Login failed";
        return { ok: false as const, message };
      }
      if (result.data?.mfa_required) {
        return { ok: false as const, message: "Multi-factor authentication is required for this account." };
      }
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      await router.navigate({ to: "/dashboard" });
      return { ok: true as const };
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    await logoutRequest();
    queryClient.setQueryData(["auth", "me"], null);
    await router.navigate({ to: "/login" });
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
      logout,
      refreshSession,
    }),
    [login, logout, refreshSession, sessionQuery.data, sessionQuery.error, sessionQuery.isLoading],
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
