import { StatusBadge } from "@/components/common/StatusBadge";
import type { FrameworkPhaseTimelineEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MissionPhaseTimelineProps {
  phases: FrameworkPhaseTimelineEntry[];
  currentPhase: string | null;
}

export function MissionPhaseTimeline({ phases, currentPhase }: MissionPhaseTimelineProps) {
  if (!phases.length) {
    return <p className="text-sm text-muted-foreground">No framework phase data available.</p>;
  }

  return (
    <ol className="relative space-y-0 border-l border-border/60 pl-4">
      {phases.map((phase, index) => {
        const isCurrent = phase.phase === currentPhase || phase.status === "active" || phase.status === "running";
        const isComplete = phase.status === "completed" || phase.status === "done";

        return (
          <li key={`${phase.phase}-${index}`} className="relative pb-6 last:pb-0">
            <span
              className={cn(
                "absolute -left-[calc(0.5rem+1px)] top-1.5 h-2.5 w-2.5 rounded-full border-2 bg-background",
                isCurrent && "border-primary bg-primary",
                isComplete && !isCurrent && "border-success bg-success",
                !isCurrent && !isComplete && "border-muted-foreground/40",
              )}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{phase.label || phase.phase}</span>
              <StatusBadge status={String(phase.status)} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
