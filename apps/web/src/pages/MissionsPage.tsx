import { Link, useNavigate } from "@tanstack/react-router";
import { type ColumnDef, type PaginationState } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { CreateMissionDialog } from "@/components/missions/CreateMissionDialog";
import { DataTable } from "@/components/common/DataTable";
import { PageHeader } from "@/components/common/PageHeader";
import { ProgressBar } from "@/components/common/ProgressBar";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState } from "@/components/common/StateViews";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMissionProgress, useMissions } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";
import type { Mission } from "@/lib/types";

function MissionProgressCell({ missionId, status }: { missionId: string; status: string }) {
  const active = !["completed", "failed", "stopped", "cancelled"].includes(status);
  const progressQuery = useMissionProgress(missionId, active);

  if (!active) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  if (progressQuery.isLoading) {
    return <div className="h-1.5 w-20 rounded-full bg-muted" />;
  }

  if (!progressQuery.data) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  return (
    <div className="w-28 space-y-1">
      <ProgressBar value={progressQuery.data.percent} />
      <span className="text-2xs text-muted-foreground">{Math.round(progressQuery.data.percent)}%</span>
    </div>
  );
}

export function MissionsPage() {
  const navigate = useNavigate();
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 20 });
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  const missionsQuery = useMissions({
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
    status: statusFilter === "all" ? undefined : statusFilter,
    search: search.trim() || undefined,
    sort_by: "created_at",
  });

  const columns = useMemo<ColumnDef<Mission>[]>(
    () => [
      {
        id: "target",
        accessorKey: "target",
        header: "Target",
        cell: ({ row }) => (
          <Link
            to="/missions/$id"
            params={{ id: row.original.id }}
            className="font-mono text-xs text-primary hover:underline"
          >
            {row.original.target}
          </Link>
        ),
      },
      {
        id: "status",
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "framework",
        header: "Framework",
        cell: ({ row }) => (
          <Badge variant="outline" className="font-mono text-2xs">
            {row.original.framework_label || row.original.pentest_framework}
          </Badge>
        ),
      },
      {
        id: "phase",
        header: "Phase",
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">{row.original.current_phase ?? "—"}</span>
        ),
      },
      {
        id: "findings",
        header: "Findings",
        cell: ({ row }) => {
          const count = row.original.findings_count ?? row.original.findings?.length ?? 0;
          return <span className="font-mono text-xs tabular-nums">{count}</span>;
        },
      },
      {
        id: "progress",
        header: "Progress",
        cell: ({ row }) => <MissionProgressCell missionId={row.original.id} status={row.original.status} />,
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Missions"
        description="Browse, launch, and manage security assessment missions."
        actions={<CreateMissionDialog onCreated={(id) => void navigate({ to: "/missions/$id", params: { id } })} />}
      />

      {missionsQuery.isError ? (
        <ErrorState message={getApiErrorMessage(missionsQuery.error)} onRetry={() => void missionsQuery.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          data={missionsQuery.data?.items ?? []}
          isLoading={missionsQuery.isLoading}
          emptyMessage="No missions yet. Start your first assessment."
          manualPagination
          pageCount={missionsQuery.data?.pages}
          pagination={pagination}
          onPaginationChange={setPagination}
          toolbar={
            <>
              <Input
                placeholder="Search directive…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPagination((p) => ({ ...p, pageIndex: 0 }));
                }}
                className="max-w-xs"
              />
              <Select
                value={statusFilter}
                onValueChange={(v) => {
                  setStatusFilter(v);
                  setPagination((p) => ({ ...p, pageIndex: 0 }));
                }}
              >
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="paused">Paused</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </>
          }
        />
      )}
    </>
  );
}
