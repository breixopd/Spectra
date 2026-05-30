import {
  Activity,
  Crosshair,
  FileText,
  FolderOpen,
  GitBranch,
  LayoutDashboard,
  PanelLeft,
  Search,
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

export const primaryNav: NavItem[] = [
  { label: "Mission Control", href: "/dashboard", icon: LayoutDashboard, description: "Live operations overview" },
  { label: "Missions", href: "/missions", icon: Crosshair, description: "Active and completed assessments" },
  { label: "Findings", href: "/findings", icon: Shield, description: "Evidence-backed vulnerabilities" },
  { label: "Attack Graph", href: "/attack-graph", icon: GitBranch, description: "Hypothesis and exploit paths" },
  { label: "Evidence", href: "/evidence", icon: FolderOpen, description: "Proof bundles and artifacts" },
  { label: "Reports", href: "/reports", icon: FileText, description: "Executive and operator reports" },
  { label: "Tools", href: "/tools", icon: Wrench, description: "Plugin registry and execution" },
  { label: "Settings", href: "/settings", icon: Settings, description: "Preferences and account" },
];

export const commandPaletteItems = [
  ...primaryNav,
  { label: "System Health", href: "/settings", icon: Activity, description: "Platform status and diagnostics" },
  { label: "Search", href: "/dashboard", icon: Search, description: "Global search (coming soon)" },
];

export const sidebarToggleIcon = PanelLeft;
