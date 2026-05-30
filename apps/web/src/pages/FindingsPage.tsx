import { Link } from "@tanstack/react-router";
import { type ColumnDef, type PaginationState, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/common/DataTable";
import { RelativeTime } from "@/components/common/DisplayPrimitives";
import { PageHeader } from "@/components/common/PageHeader";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState } from "@/components/common/StateViews";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useFindings } from "@/hooks/useFindings";
import { getApiErrorMessage } from "@/lib/api-helpers";
import {
  PROOF_ORDER,
  SEVERITY_ORDER,
  deriveExploitability,
  resolveProofStatus,
  type FindingDetail,
  type FindingSeverity,
  type FindingStatus,
  type ProofStatus,
} from "@/lib/types";

export function FindingsPage() {
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 20 });
  const [sorting, setSorting] = useState<SortingState>([{ id: "proof", desc: false }]);
  const [severityFilter, setSeverityFilter] = useState<FindingSeverity | "all">("all");
  const [statusFilter, setStatusFilter] = useState<FindingStatus | "all">("all");
  const [proofFilter, setProofFilter] = useState<ProofStatus | "all">("all");
  const [search, setSearch] = useState("");

  const findingsQuery = useFindings({
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
    severity: severityFilter === "all" ? undefined : severityFilter,
    status: statusFilter === "all" ? undefined : statusFilter,
    proof_status: proofFilter === "all" ? undefined : proofFilter,
  });

  const sortedItems = useMemo(() => {
    const items = [...(findingsQuery.data?.items ?? [])];
    const sort = sorting[0];
    if (!sort) return items;

    items.sort((a, b) => {
      let cmp = 0;
      switch (sort.id) {
        case "severity":
          cmp = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
          break;
        case "proof":
          cmp = PROOF_ORDER[resolveProofStatus(a)] - PROOF_ORDER[resolveProofStatus(b)];
          break;
        case "verified_at":
          cmp = new Date(a.verified_at ?? 0).getTime() - new Date(b.verified_at ?? 0).getTime();
          break;
        case "created_at":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "title":
          cmp = a.title.localeCompare(b.title);
          break;
        default:
          cmp = 0;
      }
      return sort.desc ? -cmp : cmp;
    });
    return items;
  }, [findingsQuery.data?.items, sorting]);

  const filteredItems = useMemo(() => {
    if (!search.trim()) return sortedItems;
    const needle = search.toLowerCase();
    return sortedItems.filter(
      (f) =>
        f.title.toLowerCase().includes(needle) ||
        f.tool_source.toLowerCase().includes(needle) ||
        f.target_label.toLowerCase().includes(needle) ||
        f.target_address.toLowerCase().includes(needle),
    );
  }, [sortedItems, search]);

  const columns = useMemo<ColumnDef<FindingDetail>[]>(
    () => [
      {
        id: "status",
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "severity",
        accessorKey: "severity",
        header: "Severity",
        cell: ({ row }) => <SeverityBadge severity={row.original.severity} />,
        enableSorting: true,
      },
      {
        id: "proof",
        header: "Proof",
        cell: ({ row }) => <ProofBadge proof={resolveProofStatus(row.original)} />,
        enableSorting: true,
      },
      {
        id: "asset",
        accessorKey: "target_label",
        header: "Asset",
        cell: ({ row }) => (
          <span className="cursor-default truncate text-xs" title={row.original.target_address}>
            {row.original.target_label}
          </span>
        ),
      },
      {
        id: "exploitability",
        header: "Exploitability",
        cell: ({ row }) => <span className="text-xs">{deriveExploitability(row.original)}</span>,
      },
      {
        id: "owner",
        header: "Owner",
        cell: () => <span className="text-xs text-muted-foreground">—</span>,
      },
      {
        id: "verified_at",
        accessorKey: "verified_at",
        header: "Last verified",
        cell: ({ row }) =>
          row.original.verified_at ? (
            <RelativeTime date={row.original.verified_at} className="text-xs" />
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
        enableSorting: true,
      },
      {
        id: "title",
        accessorKey: "title",
        header: "Finding",
        cell: ({ row }) => (
          <Link to="/findings/$id" params={{ id: row.original.id }} className="font-medium hover:text-primary">
            {row.original.title}
          </Link>
        ),
        enableSorting: true,
      },
    ],
    [],
  );

  return (
    <div>
      <PageHeader
        title="Findings"
        description="Evidence-first vulnerability inventory — verified findings surface first."
      />

      {findingsQuery.isError ? (
        <ErrorState message={getApiErrorMessage(findingsQuery.error)} onRetry={() => void findingsQuery.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          data={filteredItems}
          isLoading={findingsQuery.isLoading}
          emptyMessage="No findings match your filters."
          manualPagination
          pageCount={findingsQuery.data?.pages ?? 1}
          pagination={pagination}
          onPaginationChange={setPagination}
          manualSorting
          sorting={sorting}
          onSortingChange={setSorting}
          toolbar={
            <div className="flex flex-wrap items-center gap-2">
              <Input
                placeholder="Search title, tool, asset…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 w-56"
              />
              <Select value={severityFilter} onValueChange={(v) => setSeverityFilter(v as FindingSeverity | "all")}>
                <SelectTrigger className="h-8 w-36">
                  <SelectValue placeholder="Severity" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All severities</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="info">Info</SelectItem>
                </SelectContent>
              </Select>
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as FindingStatus | "all")}>
                <SelectTrigger className="h-8 w-36">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="verified">Verified</SelectItem>
                  <SelectItem value="potential">Potential</SelectItem>
                  <SelectItem value="exploited">Exploited</SelectItem>
                  <SelectItem value="retest_pending">Retest pending</SelectItem>
                  <SelectItem value="false_positive">False positive</SelectItem>
                  <SelectItem value="dismissed">Dismissed</SelectItem>
                </SelectContent>
              </Select>
              <Select value={proofFilter} onValueChange={(v) => setProofFilter(v as ProofStatus | "all")}>
                <SelectTrigger className="h-8 w-44">
                  <SelectValue placeholder="Proof status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All proof states</SelectItem>
                  <SelectItem value="verified">Verified</SelectItem>
                  <SelectItem value="needs_verification">Needs verification</SelectItem>
                  <SelectItem value="candidate">Candidate</SelectItem>
                  <SelectItem value="not_reproducible">Not reproducible</SelectItem>
                </SelectContent>
              </Select>
            </div>
          }
        />
      )}
    </div>
  );
}
