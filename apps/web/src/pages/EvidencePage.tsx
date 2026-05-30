import { ChevronRight, FolderTree } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  EVIDENCE_SECTION_LABELS,
  EvidenceSectionPreview,
  FindingTreeRow,
  listEvidenceSections,
  type EvidenceSectionKey,
} from "@/components/evidence/EvidencePanels";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/StateViews";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useFindingDetails } from "@/hooks/useFindings";
import { useMissionFindings, useMissions } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";
import {
  evidenceBundleHasContent,
  normalizeEvidenceBundle,
  type FindingDetail,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Selection =
  | { kind: "none" }
  | { kind: "finding"; findingId: string }
  | { kind: "section"; findingId: string; section: EvidenceSectionKey };

function missionHasEvidence(findings: FindingDetail[]): boolean {
  return findings.some((finding) => evidenceBundleHasContent(normalizeEvidenceBundle(finding.evidence_bundle)));
}

export function EvidencePage() {
  const missionsQuery = useMissions({ per_page: 100, sort_by: "created_at" });
  const [selectedMissionId, setSelectedMissionId] = useState<string>("");
  const missionId = selectedMissionId || missionsQuery.data?.items[0]?.id || "";

  const missionFindingsQuery = useMissionFindings(missionId, Boolean(missionId));
  const findingIds = useMemo(() => (missionFindingsQuery.data ?? []).map((f) => f.id), [missionFindingsQuery.data]);
  const detailQueries = useFindingDetails(findingIds, Boolean(missionId) && findingIds.length > 0);

  const findingsWithBundles = useMemo(() => {
    return detailQueries
      .map((query) => query.data)
      .filter((finding): finding is FindingDetail => Boolean(finding))
      .filter((finding) => evidenceBundleHasContent(normalizeEvidenceBundle(finding.evidence_bundle)));
  }, [detailQueries]);

  const [selection, setSelection] = useState<Selection>({ kind: "none" });

  useEffect(() => {
    setSelection({ kind: "none" });
  }, [missionId]);

  const detailsLoading = detailQueries.some((query) => query.isLoading);
  const detailsError = detailQueries.find((query) => query.isError)?.error;

  const selectedFinding =
    selection.kind === "none"
      ? null
      : findingsWithBundles.find((finding) => finding.id === (selection.kind === "finding" ? selection.findingId : selection.findingId));

  const selectedSection = selection.kind === "section" ? selection.section : null;
  const selectedBundle = selectedFinding ? normalizeEvidenceBundle(selectedFinding.evidence_bundle) : null;

  return (
    <>
      <PageHeader
        title="Evidence Browser"
        description="Immutable proof bundles across mission findings — transcripts, terminal captures, and artifact hashes."
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
        <EmptyState
          icon={FolderTree}
          title="No missions available"
          description="Run a mission to collect evidence artifacts."
        />
      ) : missionFindingsQuery.isError ? (
        <ErrorState
          message={getApiErrorMessage(missionFindingsQuery.error)}
          onRetry={() => void missionFindingsQuery.refetch()}
        />
      ) : missionFindingsQuery.isLoading || detailsLoading ? (
        <LoadingState label="Loading evidence…" />
      ) : detailsError ? (
        <ErrorState message={getApiErrorMessage(detailsError)} />
      ) : !missionHasEvidence(findingsWithBundles) ? (
        <EmptyState
          icon={FolderTree}
          title="No evidence for this mission"
          description="Findings without proof bundles will not appear here. Complete verification to attach artifacts."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
          <Card className="lg:max-h-[calc(100vh-12rem)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Evidence tree</CardTitle>
              <CardDescription>Mission → finding → section → artifact refs</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[min(32rem,calc(100vh-14rem))] px-4 pb-4">
                <ul className="space-y-1">
                  {findingsWithBundles.map((finding) => {
                    const bundle = normalizeEvidenceBundle(finding.evidence_bundle);
                    const sections = listEvidenceSections(bundle);
                    const findingSelected =
                      selection.kind !== "none" && selection.findingId === finding.id && selection.kind === "finding";

                    return (
                      <li key={finding.id} className="space-y-1">
                        <FindingTreeRow
                          finding={finding}
                          sectionCount={sections.length}
                          selected={findingSelected}
                          onSelect={() => setSelection({ kind: "finding", findingId: finding.id })}
                        />
                        <ul className="ml-6 space-y-0.5 border-l border-border/50 pl-2">
                          {sections.map((section) => {
                            const sectionSelected =
                              selection.kind === "section" &&
                              selection.findingId === finding.id &&
                              selection.section === section;
                            const childCount =
                              section === "artifact_refs"
                                ? bundle.artifact_refs.length
                                : section === "screenshots"
                                  ? bundle.screenshots.length
                                  : null;

                            return (
                              <li key={section}>
                                <button
                                  type="button"
                                  onClick={() => setSelection({ kind: "section", findingId: finding.id, section })}
                                  className={cn(
                                    "flex w-full items-center gap-1 rounded px-2 py-1.5 text-left text-xs transition-colors",
                                    sectionSelected ? "bg-muted/50 text-foreground" : "text-muted-foreground hover:bg-muted/30 hover:text-foreground",
                                  )}
                                >
                                  <ChevronRight className="h-3 w-3 shrink-0 opacity-60" />
                                  <span className="truncate">{EVIDENCE_SECTION_LABELS[section]}</span>
                                  {childCount !== null ? (
                                    <span className="ml-auto text-2xs tabular-nums text-muted-foreground">{childCount}</span>
                                  ) : null}
                                </button>
                                {section === "artifact_refs" && sectionSelected ? (
                                  <ul className="ml-4 space-y-0.5 border-l border-border/40 pl-2">
                                    {bundle.artifact_refs.map((artifact) => (
                                      <li
                                        key={`${artifact.s3_key}-${artifact.sha256 ?? "none"}`}
                                        className="truncate px-2 py-1 font-mono text-2xs text-muted-foreground"
                                        title={artifact.s3_key}
                                      >
                                        {artifact.role ?? "artifact"} · {artifact.s3_key}
                                      </li>
                                    ))}
                                  </ul>
                                ) : null}
                              </li>
                            );
                          })}
                        </ul>
                      </li>
                    );
                  })}
                </ul>
              </ScrollArea>
            </CardContent>
          </Card>

          <Card className="min-h-[24rem]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">
                {selectedFinding ? selectedFinding.title : "Select evidence to preview"}
              </CardTitle>
              <CardDescription>
                {selectedSection
                  ? EVIDENCE_SECTION_LABELS[selectedSection]
                  : selectedFinding
                    ? "All sections for this finding"
                    : "Choose a finding or section from the tree"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!selectedFinding || !selectedBundle ? (
                <p className="text-sm text-muted-foreground">
                  Preview HTTP transcripts, terminal output, scanner JSON, PoC scripts, and screenshots from the tree.
                </p>
              ) : selectedSection ? (
                <EvidenceSectionPreview section={selectedSection} bundle={selectedBundle} />
              ) : (
                <div className="space-y-4">
                  {listEvidenceSections(selectedBundle).map((section) => (
                    <div key={section}>
                      <p className="mb-2 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
                        {EVIDENCE_SECTION_LABELS[section]}
                      </p>
                      <EvidenceSectionPreview section={section} bundle={selectedBundle} />
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
