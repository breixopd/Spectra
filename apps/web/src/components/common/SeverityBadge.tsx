import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { FindingSeverity } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY_VARIANT: Record<FindingSeverity, BadgeProps["variant"]> = {
  critical: "critical",
  high: "destructive",
  medium: "warning",
  low: "info",
  info: "muted",
};

interface SeverityBadgeProps {
  severity: FindingSeverity | string;
  className?: string;
}

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  const normalized = severity.toLowerCase() as FindingSeverity;
  const variant = SEVERITY_VARIANT[normalized] ?? "outline";

  return (
    <Badge variant={variant} className={cn("uppercase tracking-wide", className)}>
      {normalized}
    </Badge>
  );
}
