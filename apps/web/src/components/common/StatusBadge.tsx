import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { FindingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<
  string,
  { label: string; variant: BadgeProps["variant"]; className?: string }
> = {
  created: { label: "Created", variant: "muted" },
  initializing: { label: "Initializing", variant: "info" },
  scoping: { label: "Scoping", variant: "info" },
  planning: { label: "Planning", variant: "info" },
  running: { label: "Running", variant: "success" },
  scanning: { label: "Scanning", variant: "success" },
  analyzing: { label: "Analyzing", variant: "success" },
  executing: { label: "Executing", variant: "success" },
  exploiting: { label: "Exploiting", variant: "warning" },
  reporting: { label: "Reporting", variant: "info" },
  completed: { label: "Completed", variant: "muted" },
  failed: { label: "Failed", variant: "destructive" },
  cancelled: { label: "Cancelled", variant: "muted" },
  stopping: { label: "Stopping", variant: "warning" },
  paused: { label: "Paused", variant: "warning" },
  potential: { label: "Potential", variant: "warning" },
  verified: { label: "Verified", variant: "success" },
  exploited: { label: "Exploited", variant: "critical" },
  false_positive: { label: "False positive", variant: "muted" },
  dismissed: { label: "Dismissed", variant: "muted" },
  retest_pending: { label: "Retest pending", variant: "info" },
  ready: { label: "Ready", variant: "success" },
  initializing_system: { label: "Initializing", variant: "info" },
  degraded: { label: "Degraded", variant: "warning" },
  error: { label: "Error", variant: "destructive" },
};

interface StatusBadgeProps {
  status: string | FindingStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  const config = STATUS_CONFIG[normalized] ?? { label: status, variant: "outline" as const };

  return (
    <Badge variant={config.variant} className={cn("capitalize", config.className, className)}>
      {config.label}
    </Badge>
  );
}
