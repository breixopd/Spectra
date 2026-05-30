import { Pause, Play, Square } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { usePauseMission, useResumeMission, useStopMission } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";
import { ACTIVE_MISSION_STATUSES } from "@/lib/types";

interface MissionLifecycleControlsProps {
  missionId: string;
  status: string;
}

export function MissionLifecycleControls({ missionId, status }: MissionLifecycleControlsProps) {
  const pauseMutation = usePauseMission();
  const resumeMutation = useResumeMission();
  const stopMutation = useStopMission();

  const isActive = ACTIVE_MISSION_STATUSES.includes(status as (typeof ACTIVE_MISSION_STATUSES)[number]);
  const isPaused = status === "paused";
  const isBusy = pauseMutation.isPending || resumeMutation.isPending || stopMutation.isPending;

  async function handlePause() {
    try {
      const result = await pauseMutation.mutateAsync(missionId);
      toast.success(result.message);
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  async function handleResume() {
    try {
      const result = await resumeMutation.mutateAsync(missionId);
      toast.success(result.message);
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  async function handleStop() {
    try {
      const result = await stopMutation.mutateAsync(missionId);
      toast.success(result.message);
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  if (!isActive && !isPaused) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {isPaused ? (
        <Button size="sm" variant="outline" disabled={isBusy} onClick={() => void handleResume()}>
          <Play className="mr-1.5 h-3.5 w-3.5" />
          Resume
        </Button>
      ) : (
        <Button size="sm" variant="outline" disabled={isBusy} onClick={() => void handlePause()}>
          <Pause className="mr-1.5 h-3.5 w-3.5" />
          Pause
        </Button>
      )}
      <Button size="sm" variant="destructive" disabled={isBusy} onClick={() => void handleStop()}>
        <Square className="mr-1.5 h-3.5 w-3.5" />
        Stop
      </Button>
    </div>
  );
}
