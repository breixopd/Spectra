import { Link } from "@tanstack/react-router";
import { Download, FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/common/PageHeader";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/StateViews";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMissionFindings, useMissions } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";
import { COMPLETED_MISSION_STATUSES, type Mission, type MissionFindingSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function deriveReportProof(finding: MissionFindingSummary) {
  if (finding.status === "verified" || finding.status === "exploited") return "verified" as const;
  if (finding.status === "false_positive" || finding.status === "dismissed") return "not_reproducible" as const;
  return "candidate" as const;
}

function ReportFindingCard({
  finding,
  included,
  onToggle,
}: {
  finding: MissionFindingSummary;
  included: boolean;
  onToggle: () => void;
}) {
  const proof = deriveReportProof(finding);
  const missingEvidence = proof === "candidate";

  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "w-full rounded-lg border p-4 text-left transition-colors",
        included ? "border-primary/50 bg-primary/5" : "border-border/60 bg-muted/10 opacity-70",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">{finding.title}</p>
          <p className="line-clamp-2 text-xs text-muted-foreground">{finding.description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SeverityBadge severity={finding.severity as never} />
          <ProofBadge proof={proof} />
        </div>
      </div>
      {missingEvidence ? (
        <p className="mt-2 text-2xs text-warning">Missing verification — include with caution</p>
      ) : null}
    </button>
  );
}

async function downloadExport(url: string, filename: string) {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Export failed (${response.status})`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export function ReportsPage() {
  const missionsQuery = useMissions({ per_page: 100, sort_by: "created_at" });
  const reportableMissions = useMemo(
    () =>
      (missionsQuery.data?.items ?? []).filter(
        (m: Mission) =>
          COMPLETED_MISSION_STATUSES.includes(m.status as (typeof COMPLETED_MISSION_STATUSES)[number]) ||
          Boolean(m.report_path),
      ),
    [missionsQuery.data?.items],
  );

  const [selectedMissionId, setSelectedMissionId] = useState<string>("");
  const missionId = selectedMissionId || reportableMissions[0]?.id || "";
  const findingsQuery = useMissionFindings(missionId, Boolean(missionId));
  const [includedIds, setIncludedIds] = useState<Set<string>>(new Set());

  const findings = findingsQuery.data ?? [];

  useEffect(() => {
    if (findings.length) {
      setIncludedIds(new Set(findings.map((f) => f.id)));
    }
  }, [missionId, findings]);

  function toggleFinding(id: string) {
    setIncludedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function exportPdf() {
    if (!missionId) return;
    try {
      await downloadExport(`/api/v1/missions/${missionId}/report/pdf`, `spectra_report_${missionId.slice(0, 8)}.pdf`);
      toast.success("PDF downloaded");
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  async function exportJson() {
    if (!missionId) return;
    try {
      await downloadExport(`/api/v1/missions/${missionId}/export/json`, `spectra_export_${missionId.slice(0, 8)}.json`);
      toast.success("JSON downloaded");
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  function exportMarkdownStub() {
    toast.info("Markdown export is not yet available — use PDF or JSON");
  }

  return (
    <>
      <PageHeader
        title="Reports"
        description="Executive summaries and operator-grade export workflows."
        actions={
          missionId ? (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => void exportPdf()}>
                <Download className="mr-1.5 h-3.5 w-3.5" />
                PDF
              </Button>
              <Button size="sm" variant="outline" onClick={() => void exportJson()}>
                <Download className="mr-1.5 h-3.5 w-3.5" />
                JSON
              </Button>
              <Button size="sm" variant="ghost" onClick={exportMarkdownStub}>
                Markdown
              </Button>
            </div>
          ) : null
        }
      />

      {missionsQuery.isLoading ? (
        <LoadingState label="Loading missions…" />
      ) : missionsQuery.isError ? (
        <ErrorState message={getApiErrorMessage(missionsQuery.error)} onRetry={() => void missionsQuery.refetch()} />
      ) : reportableMissions.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No reports yet"
          description="Complete a mission to generate exportable reports."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-12">
          <Card className="lg:col-span-4">
            <CardHeader>
              <CardTitle className="text-base">Mission reports</CardTitle>
              <CardDescription>Select a mission to compose its report</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select
                value={missionId}
                onValueChange={(id) => {
                  setSelectedMissionId(id);
                  setIncludedIds(new Set());
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select mission" />
                </SelectTrigger>
                <SelectContent>
                  {reportableMissions.map((mission) => (
                    <SelectItem key={mission.id} value={mission.id}>
                      {mission.target}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <ul className="divide-y divide-border/60 rounded-lg border border-border">
                {reportableMissions.slice(0, 8).map((mission) => (
                  <li key={mission.id}>
                    <Link
                      to="/missions/$id"
                      params={{ id: mission.id }}
                      className="flex items-center justify-between px-3 py-2 text-sm hover:bg-muted/20"
                    >
                      <span className="truncate font-mono text-xs">{mission.target}</span>
                      <StatusBadge status={mission.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="lg:col-span-8">
            <CardHeader>
              <CardTitle className="text-base">Report builder</CardTitle>
              <CardDescription>
                {includedIds.size} of {findings.length} findings included
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {findingsQuery.isLoading ? (
                <LoadingState label="Loading findings…" />
              ) : findings.length === 0 ? (
                <EmptyState title="No findings" description="This mission has no findings to include." />
              ) : (
                findings.map((finding) => (
                  <ReportFindingCard
                    key={finding.id}
                    finding={finding}
                    included={includedIds.has(finding.id)}
                    onToggle={() => toggleFinding(finding.id)}
                  />
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
