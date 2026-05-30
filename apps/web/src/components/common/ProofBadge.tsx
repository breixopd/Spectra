import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { ProofStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROOF_CONFIG: Record<ProofStatus, { label: string; variant: BadgeProps["variant"] }> = {
  verified: { label: "Verified", variant: "success" },
  needs_verification: { label: "Needs verification", variant: "warning" },
  candidate: { label: "Candidate", variant: "muted" },
  not_reproducible: { label: "Not reproducible", variant: "outline" },
};

interface ProofBadgeProps {
  proof: ProofStatus;
  className?: string;
}

export function ProofBadge({ proof, className }: ProofBadgeProps) {
  const config = PROOF_CONFIG[proof];
  return (
    <Badge variant={config.variant} className={cn(className)}>
      {config.label}
    </Badge>
  );
}
