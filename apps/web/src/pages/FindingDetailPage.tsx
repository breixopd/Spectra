import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import {
  ArtifactRefsTable,
  EvidenceSectionPreview,
  ScreenshotGallery,
  TextEvidenceBlock,
} from "@/components/evidence/EvidencePanels";
import { KeyValue, RelativeTime, ScoreChip } from "@/components/common/DisplayPrimitives";
import { PageHeader } from "@/components/common/PageHeader";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useFinding, useRetestFinding } from "@/hooks/useFindings";
import { getApiErrorMessage } from "@/lib/api-helpers";
import { deriveExploitability, evidenceBundleHasContent, normalizeEvidenceBundle, resolveProofStatus } from "@/lib/types";

function hasTabContent(value: string | null | undefined): boolean {
  return Boolean(value?.trim());
}

export function FindingDetailPage() {
  const { id } = useParams({ from: "/_authenticated/findings/$id" });
  const findingQuery = useFinding(id);
  const retestMutation = useRetestFinding();

  if (findingQuery.isLoading) {
    return <LoadingState label="Loading finding…" />;
  }

  if (findingQuery.isError || !findingQuery.data) {
    return (
      <ErrorState
        message={getApiErrorMessage(findingQuery.error)}
        onRetry={() => void findingQuery.refetch()}
      />
    );
  }

  const finding = findingQuery.data;
  const proof = resolveProofStatus(finding);
  const bundle = normalizeEvidenceBundle(finding.evidence_bundle);
  const hasBundle = evidenceBundleHasContent(bundle);

  const tabs = [
    { id: "http", label: "HTTP", visible: hasTabContent(bundle.http_transcript) },
    { id: "terminal", label: "Terminal", visible: hasTabContent(bundle.terminal_output) || hasTabContent(bundle.command) },
    { id: "screenshots", label: "Screenshots", visible: bundle.screenshots.length > 0 },
    { id: "scanner", label: "Scanner", visible: hasTabContent(bundle.scanner_output) },
    { id: "poc", label: "PoC", visible: hasTabContent(bundle.poc_script) },
    { id: "artifacts", label: "Artifacts", visible: bundle.artifact_refs.length > 0 },
  ].filter((tab) => tab.visible);

  const defaultTab = tabs[0]?.id ?? "http";

  const handleRetest = async () => {
    try {
      await retestMutation.mutateAsync(id);
      toast.success("Retest requested", { description: "Finding status set to retest_pending." });
    } catch (error) {
      toast.error("Retest failed", { description: getApiErrorMessage(error) });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/findings">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Findings
          </Link>
        </Button>
      </div>

      <PageHeader
        title={finding.title}
        description={finding.description ?? "No description provided."}
        meta={
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <StatusBadge status={finding.status} />
            <SeverityBadge severity={finding.severity} />
            <ProofBadge proof={proof} />
            <ScoreChip score={finding.cvss_score} />
            {finding.cve_id ? (
              <span className="rounded-md border border-border px-2 py-0.5 font-mono text-xs">{finding.cve_id}</span>
            ) : null}
            <span className="text-xs text-muted-foreground">
              Last verified{" "}
              {finding.verified_at ? <RelativeTime date={finding.verified_at} className="text-xs" /> : "—"}
            </span>
          </div>
        }
        actions={
          <Button variant="outline" size="sm" onClick={() => void handleRetest()} disabled={retestMutation.isPending}>
            <RefreshCw className={retestMutation.isPending ? "mr-1 h-4 w-4 animate-spin" : "mr-1 h-4 w-4"} />
            Request retest
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Evidence bundle</CardTitle>
            <CardDescription>Replayable proof artifacts — the hero of this finding</CardDescription>
          </CardHeader>
          <CardContent>
            {!hasBundle ? (
              <p className="text-sm text-muted-foreground">
                No structured evidence attached yet. Verified findings should include transcript, terminal, or artifact
                references in the evidence bundle.
              </p>
            ) : tabs.length === 0 ? (
              <p className="text-sm text-muted-foreground">Evidence bundle is empty.</p>
            ) : (
              <Tabs defaultValue={defaultTab}>
                <TabsList className="flex h-auto flex-wrap gap-1">
                  {tabs.map((tab) => (
                    <TabsTrigger key={tab.id} value={tab.id}>
                      {tab.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
                <TabsContent value="http">
                  <EvidenceSectionPreview section="http_transcript" bundle={bundle} />
                </TabsContent>
                <TabsContent value="terminal">
                  <div className="space-y-3">
                    {hasTabContent(bundle.command) ? (
                      <TextEvidenceBlock label="Command" content={bundle.command} emptyLabel="" />
                    ) : null}
                    <EvidenceSectionPreview section="terminal_output" bundle={bundle} />
                  </div>
                </TabsContent>
                <TabsContent value="screenshots">
                  <ScreenshotGallery screenshots={bundle.screenshots} />
                </TabsContent>
                <TabsContent value="scanner">
                  <EvidenceSectionPreview section="scanner_output" bundle={bundle} />
                </TabsContent>
                <TabsContent value="poc">
                  <EvidenceSectionPreview section="poc_script" bundle={bundle} />
                </TabsContent>
                <TabsContent value="artifacts">
                  <ArtifactRefsTable artifacts={bundle.artifact_refs} />
                </TabsContent>
              </Tabs>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Claim</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <KeyValue label="Tool" value={finding.tool_source} />
              <KeyValue label="Target" value={finding.target_label} />
              <KeyValue label="Address" value={finding.target_address} mono />
              <KeyValue label="Exploitability" value={deriveExploitability(finding)} />
              <KeyValue label="Discovered" value={<RelativeTime date={finding.created_at} />} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Replay steps</CardTitle>
              <CardDescription>Instructions to reproduce the issue</CardDescription>
            </CardHeader>
            <CardContent>
              <TextEvidenceBlock
                label="Replay"
                content={bundle.replay_steps}
                emptyLabel="No replay instructions in the evidence bundle."
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Remediation</CardTitle>
            </CardHeader>
            <CardContent>
              <TextEvidenceBlock
                label="Fix"
                content={bundle.remediation}
                emptyLabel={finding.description ?? "No remediation guidance attached."}
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
