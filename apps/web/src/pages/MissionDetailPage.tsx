import { Link, useParams } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { FileText, Radio } from "lucide-react";
import { useMemo } from "react";

import { AttackGraphCanvas } from "@/components/attack-graph/AttackGraphCanvas";
import { DataTable } from "@/components/common/DataTable";
import { KeyValue, RelativeTime } from "@/components/common/DisplayPrimitives";
import { PageHeader } from "@/components/common/PageHeader";
import { ProgressBar } from "@/components/common/ProgressBar";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/StateViews";
import { MissionLifecycleControls } from "@/components/missions/MissionLifecycleControls";
import { MissionPhaseTimeline } from "@/components/missions/MissionPhaseTimeline";
import { MissionTaskTreeView } from "@/components/missions/MissionTaskTreeView";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMissionEventsFeed } from "@/hooks/useMissionEventsFeed";
import {
  useMission,
  useMissionArtifacts,
  useMissionFindings,
  useMissionProgress,
  useMissionTaskTree,
} from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";
import { ACTIVE_MISSION_STATUSES, type MissionFindingSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function deriveMissionProof(finding: MissionFindingSummary) {
  if (finding.status === "verified" || finding.status === "exploited") return "verified" as const;
  if (finding.status === "false_positive" || finding.status === "dismissed") return "not_reproducible" as const;
  if (finding.status === "retest_pending") return "needs_verification" as const;
  return "candidate" as const;
}

export function MissionDetailPage() {
  const { id } = useParams({ from: "/_authenticated/missions/$id" });
  const missionQuery = useMission(id);
  const progressQuery = useMissionProgress(
    id,
    Boolean(missionQuery.data && ACTIVE_MISSION_STATUSES.includes(
      missionQuery.data.status as (typeof ACTIVE_MISSION_STATUSES)[number],
    )),
  );
  const taskTreeQuery = useMissionTaskTree(id);
  const findingsQuery = useMissionFindings(id);
  const artifactsQuery = useMissionArtifacts(id);
  const { events, connected } = useMissionEventsFeed(100);

  const missionEvents = useMemo(
    () =>
      events.filter((event) => {
        const data = event.data;
        if (!data) return event.type.startsWith("mission") || event.type === "log";
        const missionId = data.mission_id ?? data.missionId ?? data.id;
        return !missionId || String(missionId) === id;
      }),
    [events, id],
  );

  const findingColumns = useMemo<ColumnDef<MissionFindingSummary>[]>(
    () => [
      {
        id: "severity",
        header: "Severity",
        cell: ({ row }) => <SeverityBadge severity={row.original.severity as never} />,
      },
      {
        id: "proof",
        header: "Proof",
        cell: ({ row }) => <ProofBadge proof={deriveMissionProof(row.original)} />,
      },
      {
        id: "title",
        accessorKey: "title",
        header: "Title",
        cell: ({ row }) => (
          <Link to="/findings/$id" params={{ id: row.original.id }} className="text-sm hover:text-primary">
            {row.original.title}
          </Link>
        ),
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "tool",
        accessorKey: "tool_source",
        header: "Tool",
        cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.tool_source}</span>,
      },
    ],
    [],
  );

  if (missionQuery.isLoading) {
    return <LoadingState label="Loading mission…" />;
  }

  if (missionQuery.isError || !missionQuery.data) {
    return (
      <ErrorState
        message={getApiErrorMessage(missionQuery.error)}
        onRetry={() => void missionQuery.refetch()}
      />
    );
  }

  const mission = missionQuery.data;
  const progress = progressQuery.data;

  return (
    <>
      <PageHeader
        title={mission.target}
        description={mission.directive ?? "Security assessment mission"}
        meta={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={mission.status} />
            <Badge variant="outline">{mission.framework_label}</Badge>
            {mission.current_phase ? (
              <span className="text-xs text-muted-foreground">Phase: {mission.current_phase}</span>
            ) : null}
          </div>
        }
        actions={<MissionLifecycleControls missionId={id} status={mission.status} />}
      />

      {progress ? (
        <div className="mb-6 space-y-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{progress.phase}</span>
            <span className="font-mono tabular-nums">{Math.round(progress.percent)}%</span>
          </div>
          <ProgressBar value={progress.percent} />
        </div>
      ) : null}

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="tasks">Task tree</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="findings">Findings</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Phase timeline</CardTitle>
              <CardDescription>{mission.framework_label} progress</CardDescription>
            </CardHeader>
            <CardContent>
              <MissionPhaseTimeline
                phases={mission.framework_phase_timeline}
                currentPhase={mission.current_phase}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Mission details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <KeyValue label="Mission ID" value={mission.id} mono />
              <KeyValue label="Framework" value={mission.pentest_framework} />
              <KeyValue
                label="Findings"
                value={String(mission.findings_count ?? mission.findings?.length ?? 0)}
              />
              <KeyValue label="Tools run" value={String(mission.tools_run?.length ?? 0)} />
              {mission.attack_surface ? (
                <KeyValue
                  label="Attack surface"
                  value={`${mission.attack_surface.hosts ?? 0} hosts · ${mission.attack_surface.services ?? 0} services`}
                />
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tasks">
          {taskTreeQuery.isLoading ? (
            <LoadingState label="Loading task tree…" />
          ) : taskTreeQuery.isError ? (
            <ErrorState message={getApiErrorMessage(taskTreeQuery.error)} onRetry={() => void taskTreeQuery.refetch()} />
          ) : (
            <MissionTaskTreeView tasks={taskTreeQuery.data?.tasks ?? []} />
          )}
        </TabsContent>

        <TabsContent value="graph">
          <AttackGraphCanvas
            taskTree={taskTreeQuery.data}
            findings={findingsQuery.data}
            isLoading={taskTreeQuery.isLoading || findingsQuery.isLoading}
          />
        </TabsContent>

        <TabsContent value="findings">
          {findingsQuery.isError ? (
            <ErrorState message={getApiErrorMessage(findingsQuery.error)} onRetry={() => void findingsQuery.refetch()} />
          ) : (
            <DataTable
              columns={findingColumns}
              data={findingsQuery.data ?? []}
              isLoading={findingsQuery.isLoading}
              emptyMessage="No findings for this mission yet."
            />
          )}
        </TabsContent>

        <TabsContent value="activity">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Radio className={cn("h-4 w-4", connected ? "text-success" : "text-muted-foreground")} />
                Live activity
              </CardTitle>
              <CardDescription>Mission events and logs from /ws</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-96 px-4 pb-4">
                {mission.logs.length === 0 && missionEvents.length === 0 ? (
                  <EmptyState title="No activity yet" description="Events will appear as the mission runs." />
                ) : (
                  <ul className="space-y-2 font-mono text-2xs">
                    {missionEvents.map((event) => (
                      <li key={event.id} className="rounded-md border border-border/40 bg-muted/10 px-2 py-1.5">
                        <div className="flex justify-between gap-2">
                          <span className="text-primary">{event.type}</span>
                          <RelativeTime date={event.receivedAt} />
                        </div>
                        {event.data ? (
                          <pre className="mt-1 max-h-20 overflow-hidden text-muted-foreground">
                            {JSON.stringify(event.data).slice(0, 200)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                    {mission.logs.slice(-50).reverse().map((log, index) => (
                      <li key={`log-${index}`} className="text-muted-foreground">
                        {log}
                      </li>
                    ))}
                  </ul>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="artifacts">
          {artifactsQuery.isLoading ? (
            <LoadingState label="Loading artifacts…" />
          ) : artifactsQuery.isError ? (
            <ErrorState
              message={getApiErrorMessage(artifactsQuery.error)}
              onRetry={() => void artifactsQuery.refetch()}
            />
          ) : !artifactsQuery.data?.length ? (
            <EmptyState icon={FileText} title="No artifacts" description="Proof bundles and outputs will appear here." />
          ) : (
            <div className="rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2 font-medium">File</th>
                    <th className="px-4 py-2 font-medium">Kind</th>
                    <th className="px-4 py-2 font-medium">Size</th>
                    <th className="px-4 py-2 font-medium">SHA256</th>
                  </tr>
                </thead>
                <tbody>
                  {artifactsQuery.data.map((artifact) => (
                    <tr key={artifact.id} className="border-b border-border/60 last:border-0">
                      <td className="px-4 py-2 font-mono text-xs">{artifact.filename}</td>
                      <td className="px-4 py-2">
                        <Badge variant="outline">{artifact.kind}</Badge>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs tabular-nums">
                        {(artifact.size / 1024).toFixed(1)} KB
                      </td>
                      <td className="px-4 py-2 font-mono text-2xs text-muted-foreground">
                        {artifact.sha256.slice(0, 12)}…
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
