import { Link } from "@tanstack/react-router";
import { Activity, AlertTriangle, Radio, Shield, ShieldAlert, Target } from "lucide-react";

import { RelativeTime } from "@/components/common/DisplayPrimitives";
import { PageHeader } from "@/components/common/PageHeader";
import { ProgressBar } from "@/components/common/ProgressBar";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/StateViews";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useFindings } from "@/hooks/useFindings";
import { useMissionEventsFeed } from "@/hooks/useMissionEventsFeed";
import { useMissionProgress, useMissions, useMissionsSummary } from "@/hooks/useMissions";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { getApiErrorMessage } from "@/lib/api-helpers";
import { ACTIVE_MISSION_STATUSES, resolveProofStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ActiveMissionCardProps {
  id: string;
  target: string;
  status: string;
  subtitle?: string;
}

function ActiveMissionCard({ id, target, status, subtitle }: ActiveMissionCardProps) {
  const isActive = ACTIVE_MISSION_STATUSES.includes(status as (typeof ACTIVE_MISSION_STATUSES)[number]);
  const progressQuery = useMissionProgress(id, isActive);

  return (
    <Link
      to="/missions/$id"
      params={{ id }}
      className="block rounded-md border border-border/60 bg-muted/20 px-3 py-2 transition-colors hover:bg-muted/40"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs">{target}</p>
          <p className="truncate text-2xs text-muted-foreground">{subtitle ?? id.slice(0, 8)}</p>
        </div>
        <div className="flex items-center gap-2">
          {isActive ? <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-success" /> : null}
          <StatusBadge status={status} />
        </div>
      </div>
      {isActive && progressQuery.data ? (
        <div className="mt-2 space-y-1">
          <ProgressBar value={progressQuery.data.percent} />
          <p className="text-2xs text-muted-foreground">
            {progressQuery.data.phase} · {Math.round(progressQuery.data.percent)}%
          </p>
        </div>
      ) : isActive && progressQuery.isLoading ? (
        <div className="mt-2 h-1.5 w-full rounded-full bg-muted" />
      ) : null}
    </Link>
  );
}

export function MissionControlPage() {
  const { events, connected } = useMissionEventsFeed();
  const missionsQuery = useMissions({ per_page: 20, sort_by: "created_at" });
  const summaryQuery = useMissionsSummary({ limit: 10 });
  const findingsQuery = useFindings({ per_page: 5, status: "verified" });
  const systemQuery = useSystemStatus({ refetchInterval: connected ? 60_000 : 30_000 });

  const activeFromSummary =
    summaryQuery.data?.missions.filter((m) =>
      ACTIVE_MISSION_STATUSES.includes(m.status as (typeof ACTIVE_MISSION_STATUSES)[number]),
    ) ?? [];

  const activeFromList =
    missionsQuery.data?.items.filter((m) =>
      ACTIVE_MISSION_STATUSES.includes(m.status as (typeof ACTIVE_MISSION_STATUSES)[number]),
    ) ?? [];

  const activeMissions =
    activeFromSummary.length > 0
      ? activeFromSummary.map((m) => ({ id: m.id, target: m.target, status: m.status, subtitle: m.directive }))
      : activeFromList.map((m) => ({ id: m.id, target: m.target, status: m.status, subtitle: m.directive ?? undefined }));

  const riskTotals = summaryQuery.data?.totals;
  const missionsLoading = summaryQuery.isLoading && missionsQuery.isLoading;
  const missionsError = summaryQuery.isError && missionsQuery.isError;

  return (
    <TooltipProvider>
      <PageHeader
        title="Mission Control"
        description="What is happening right now — active assessments, verified risk, and platform health."
        meta={
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Radio className={cn("h-3.5 w-3.5", connected ? "text-success" : "text-muted-foreground")} />
            {connected ? "Live feed connected" : "Polling fallback — websocket reconnecting"}
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-8">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-4 w-4 text-muted-foreground" />
                Active missions
              </CardTitle>
              <CardDescription>Assessments currently in flight</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {missionsLoading ? (
                <LoadingState label="Loading missions…" />
              ) : missionsError ? (
                <ErrorState
                  message={getApiErrorMessage(summaryQuery.error ?? missionsQuery.error)}
                  onRetry={() => {
                    void summaryQuery.refetch();
                    void missionsQuery.refetch();
                  }}
                />
              ) : activeMissions.length === 0 ? (
                <EmptyState
                  icon={Target}
                  title="No active missions"
                  description="Start an assessment from Missions when you're ready to engage a target."
                />
              ) : (
                activeMissions.slice(0, 6).map((mission) => (
                  <ActiveMissionCard key={mission.id} {...mission} />
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-muted-foreground" />
                Recent verified findings
              </CardTitle>
              <CardDescription>Evidence-backed issues confirmed by verification</CardDescription>
            </CardHeader>
            <CardContent>
              {findingsQuery.isLoading ? (
                <LoadingState label="Loading findings…" />
              ) : findingsQuery.isError ? (
                <ErrorState message={getApiErrorMessage(findingsQuery.error)} onRetry={() => void findingsQuery.refetch()} />
              ) : !findingsQuery.data?.items.length ? (
                <EmptyState
                  icon={Shield}
                  title="No verified findings yet"
                  description="Verified issues will appear here as missions complete verification gates."
                />
              ) : (
                <ul className="divide-y divide-border/60">
                  {findingsQuery.data.items.map((finding) => (
                    <li key={finding.id}>
                      <Link
                        to="/findings/$id"
                        params={{ id: finding.id }}
                        className="-mx-2 flex items-start justify-between gap-3 rounded-md px-2 py-3 transition-colors hover:bg-muted/20"
                      >
                        <div className="min-w-0 space-y-1">
                          <p className="truncate text-sm font-medium">{finding.title}</p>
                          <div className="flex flex-wrap items-center gap-2">
                            <SeverityBadge severity={finding.severity} />
                            <ProofBadge proof={resolveProofStatus(finding)} />
                            <span className="text-2xs text-muted-foreground">{finding.tool_source}</span>
                          </div>
                        </div>
                        <RelativeTime date={finding.created_at} className="shrink-0 text-2xs text-muted-foreground" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-muted-foreground" />
                Risk summary
              </CardTitle>
              <CardDescription>Finding counts across recent missions</CardDescription>
            </CardHeader>
            <CardContent>
              {summaryQuery.isLoading ? (
                <LoadingState label="Loading summary…" />
              ) : summaryQuery.isError ? (
                <ErrorState message={getApiErrorMessage(summaryQuery.error)} onRetry={() => void summaryQuery.refetch()} />
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  {(["critical", "high", "medium", "low"] as const).map((severity) => (
                    <div key={severity} className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                      <p className="text-2xs uppercase tracking-wide text-muted-foreground">{severity}</p>
                      <p className="font-mono text-lg tabular-nums">{riskTotals?.[severity] ?? 0}</p>
                    </div>
                  ))}
                  <div className="col-span-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                    <p className="text-2xs uppercase tracking-wide text-muted-foreground">Total findings</p>
                    <p className="font-mono text-lg tabular-nums">{riskTotals?.total ?? 0}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-muted-foreground" />
                System health
              </CardTitle>
              <CardDescription>{systemQuery.data?.message ?? "Platform component status"}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {systemQuery.isLoading ? (
                <LoadingState label="Checking system…" />
              ) : systemQuery.isError ? (
                <ErrorState message={getApiErrorMessage(systemQuery.error)} onRetry={() => void systemQuery.refetch()} />
              ) : systemQuery.data ? (
                <>
                  <div className="flex items-center justify-between">
                    <StatusBadge status={systemQuery.data.status} />
                    <RelativeTime date={systemQuery.data.timestamp} className="text-2xs text-muted-foreground" />
                  </div>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Database</span>
                      <Badge variant="outline">{systemQuery.data.database.status}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Cache</span>
                      <Badge variant="outline">{systemQuery.data.cache.status}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Tools ready</span>
                      <span className="font-mono tabular-nums">
                        {systemQuery.data.tool_stats.ready}/{systemQuery.data.tool_stats.total}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">RAG</span>
                      <Badge variant="outline">{systemQuery.data.rag_status}</Badge>
                    </div>
                  </div>
                </>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Live event feed</CardTitle>
              <CardDescription>Mission and finding events from /ws</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-64 px-4 pb-4">
                {events.length === 0 ? (
                  <p className="py-8 text-center text-xs text-muted-foreground">Waiting for events…</p>
                ) : (
                  <ul className="space-y-2">
                    {events.map((event) => (
                      <li key={event.id} className="rounded-md border border-border/40 bg-muted/10 px-2 py-1.5 font-mono text-2xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-primary">{event.type}</span>
                          <RelativeTime date={event.receivedAt} />
                        </div>
                        {event.data ? (
                          <pre className="mt-1 max-h-16 overflow-hidden text-muted-foreground">
                            {JSON.stringify(event.data).slice(0, 160)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </TooltipProvider>
  );
}
