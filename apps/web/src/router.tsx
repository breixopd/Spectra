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
import { EvidencePage } from "@/pages/EvidencePage";
import { ReportsPage } from "@/pages/ReportsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { ToolsPage } from "@/pages/ToolsPage";
import { FindingDetailPage } from "@/pages/FindingDetailPage";
import { FindingsPage } from "@/pages/FindingsPage";
import { LoginPage } from "@/pages/LoginPage";
import { MissionControlPage } from "@/pages/MissionControlPage";
import { MissionDetailPage } from "@/pages/MissionDetailPage";
import { MissionsPage } from "@/pages/MissionsPage";

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
  component: LoginPage,
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
  component: MissionControlPage,
});

const missionsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/missions",
  component: MissionsPage,
});

const missionDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/missions/$id",
  component: MissionDetailPage,
});

const findingsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/findings",
  component: FindingsPage,
});

const findingDetailRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/findings/$id",
  component: FindingDetailPage,
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
  component: EvidencePage,
});

const reportsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/reports",
  component: ReportsPage,
});

const toolsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/tools",
  component: ToolsPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/settings",
  component: SettingsPage,
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
