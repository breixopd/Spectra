import { useState } from "react";

import { AttackGraphCanvas } from "@/components/attack-graph/AttackGraphCanvas";
import { PageHeader } from "@/components/common/PageHeader";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMissionFindings, useMissionTaskTree, useMissions } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";

export function AttackGraphPage() {
  const missionsQuery = useMissions({ per_page: 50, sort_by: "created_at" });
  const [selectedMissionId, setSelectedMissionId] = useState<string>("");

  const missionId = selectedMissionId || missionsQuery.data?.items[0]?.id || "";
  const taskTreeQuery = useMissionTaskTree(missionId, Boolean(missionId));
  const findingsQuery = useMissionFindings(missionId, Boolean(missionId));

  return (
    <>
      <PageHeader
        title="Attack Graph"
        description="Evidence-guided attack tree with semantic node types and selected-path highlighting."
        actions={
          missionsQuery.isLoading ? null : (
            <Select value={missionId} onValueChange={setSelectedMissionId}>
              <SelectTrigger className="w-[280px]">
                <SelectValue placeholder="Select mission" />
              </SelectTrigger>
              <SelectContent>
                {(missionsQuery.data?.items ?? []).map((mission) => (
                  <SelectItem key={mission.id} value={mission.id}>
                    {mission.target}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )
        }
      />

      {missionsQuery.isError ? (
        <ErrorState message={getApiErrorMessage(missionsQuery.error)} onRetry={() => void missionsQuery.refetch()} />
      ) : missionsQuery.isLoading ? (
        <LoadingState label="Loading missions…" />
      ) : !missionId ? (
        <AttackGraphCanvas taskTree={undefined} findings={undefined} />
      ) : (
        <AttackGraphCanvas
          taskTree={taskTreeQuery.data}
          findings={findingsQuery.data}
          isLoading={taskTreeQuery.isLoading || findingsQuery.isLoading}
        />
      )}
    </>
  );
}
