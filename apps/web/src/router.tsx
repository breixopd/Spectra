import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Navigate,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { AppShell } from "@/components/layout/AppShell";

export interface RouterContext {
  auth: {
    isAuthenticated: boolean;
    isLoading: boolean;
  };
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: lazyRouteComponent(() => import("@/pages/LoginPage"), "LoginPage"),
  beforeLoad: ({ context }) => {
    if (context.auth.isAuthenticated) {
      throw redirect({ to: "/dashboard" });
    }
  },
});

const authenticatedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_authenticated",
  component: AppShell,
  beforeLoad: ({ context }) => {
    if (!context.auth.isAuthenticated) {
      throw redirect({ to: "/login" });
    }
  },
});

const indexRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/dashboard",
  component: lazyRouteComponent(() => import("@/pages/MissionControlPage"), "MissionControlPage"),
});

const missionsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/missions",
  component: lazyRouteComponent(() => import("@/pages/MissionsPage"), "MissionsPage"),
});

const missionDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/missions/$id",
  component: lazyRouteComponent(() => import("@/pages/MissionDetailPage"), "MissionDetailPage"),
});

const findingsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/findings",
  component: lazyRouteComponent(() => import("@/pages/FindingsPage"), "FindingsPage"),
});

const findingDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/findings/$id",
  component: lazyRouteComponent(() => import("@/pages/FindingDetailPage"), "FindingDetailPage"),
});

// Lazy: the attack graph pulls in elkjs (~1.4 MB), keep it out of the main chunk.
const attackGraphRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/attack-graph",
  component: lazyRouteComponent(() => import("@/pages/AttackGraphPage"), "AttackGraphPage"),
});

const evidenceRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/evidence",
  component: lazyRouteComponent(() => import("@/pages/EvidencePage"), "EvidencePage"),
});

const reportsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/reports",
  component: lazyRouteComponent(() => import("@/pages/ReportsPage"), "ReportsPage"),
});

const toolsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/tools",
  component: lazyRouteComponent(() => import("@/pages/ToolsPage"), "ToolsPage"),
});

const settingsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/settings",
  component: lazyRouteComponent(() => import("@/pages/SettingsPage"), "SettingsPage"),
});

const catchAllRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "$",
  component: () => <Navigate to="/dashboard" replace />,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authenticatedRoute.addChildren([
    indexRoute,
    missionsRoute,
    missionDetailRoute,
    findingsRoute,
    findingDetailRoute,
    attackGraphRoute,
    evidenceRoute,
    reportsRoute,
    toolsRoute,
    settingsRoute,
  ]),
  catchAllRoute,
]);

export const router = createRouter({
  routeTree,
  context: {
    auth: {
      isAuthenticated: false,
      isLoading: true,
    },
  } satisfies RouterContext,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
