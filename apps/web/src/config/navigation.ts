import {
  Activity,
  Crosshair,
  FileText,
  FolderOpen,
  GitBranch,
  LayoutDashboard,
  PanelLeft,
  Settings,
  Shield,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  description?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const navGroups: NavGroup[] = [
  {
    label: "Operations",
    items: [
      { label: "Mission Control", href: "/dashboard", icon: LayoutDashboard, description: "Live operations overview" },
      { label: "Missions", href: "/missions", icon: Crosshair, description: "Active and completed assessments" },
      { label: "Findings", href: "/findings", icon: Shield, description: "Evidence-backed vulnerabilities" },
      { label: "Attack Graph", href: "/attack-graph", icon: GitBranch, description: "Hypothesis and exploit paths" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Evidence", href: "/evidence", icon: FolderOpen, description: "Proof bundles and artifacts" },
      { label: "Reports", href: "/reports", icon: FileText, description: "Executive and operator reports" },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Tools", href: "/tools", icon: Wrench, description: "Plugin registry and execution" },
      { label: "Settings", href: "/settings", icon: Settings, description: "Account, billing, and diagnostics" },
    ],
  },
];

/** Flat list for command palette and mobile nav */
export const primaryNav: NavItem[] = navGroups.flatMap((group) => group.items);

export const commandPaletteItems: NavItem[] = [
  ...primaryNav,
  { label: "System diagnostics", href: "/settings", icon: Activity, description: "Platform health and API keys" },
];

export const sidebarToggleIcon = PanelLeft;
