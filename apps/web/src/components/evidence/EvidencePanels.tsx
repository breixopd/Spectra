import { FileText, ImageIcon } from "lucide-react";

import { RelativeTime } from "@/components/common/DisplayPrimitives";
import { ProofBadge } from "@/components/common/ProofBadge";
import { SeverityBadge } from "@/components/common/SeverityBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  resolveProofStatus,
  type ArtifactRef,
  type EvidenceBundle,
  type FindingDetail,
  type FindingEvidenceSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function TextEvidenceBlock({
  label,
  content,
  emptyLabel,
  className,
}: {
  label: string;
  content: string | null | undefined;
  emptyLabel: string;
  className?: string;
}) {
  if (!content?.trim()) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <div className={cn("rounded-md border border-border/60 bg-muted/10", className)}>
      <div className="border-b border-border/40 px-3 py-1.5 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <pre className="max-h-96 overflow-auto p-3 font-mono text-xs leading-relaxed text-foreground/90">{content}</pre>
    </div>
  );
}

export function ScreenshotGallery({ screenshots }: { screenshots: string[] }) {
  if (screenshots.length === 0) {
    return <p className="text-sm text-muted-foreground">No screenshots attached.</p>;
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {screenshots.map((src, index) => (
        <figure key={`${src.slice(0, 32)}-${index}`} className="overflow-hidden rounded-md border border-border/60 bg-muted/10">
          <img
            src={src}
            alt={`Evidence screenshot ${index + 1}`}
            className="max-h-64 w-full object-contain bg-background"
            loading="lazy"
          />
          <figcaption className="flex items-center gap-1 border-t border-border/40 px-2 py-1 text-2xs text-muted-foreground">
            <ImageIcon className="h-3 w-3" />
            Screenshot {index + 1}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

export function ArtifactRefsTable({ artifacts }: { artifacts: ArtifactRef[] }) {
  if (artifacts.length === 0) {
    return <p className="text-sm text-muted-foreground">No immutable artifact references.</p>;
  }

  return (
    <div className="overflow-hidden rounded-md border border-border/60">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-2xs">S3 key</TableHead>
            <TableHead className="text-2xs">SHA-256</TableHead>
            <TableHead className="text-2xs">MIME</TableHead>
            <TableHead className="text-2xs">Role</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {artifacts.map((artifact) => (
            <TableRow key={`${artifact.s3_key}-${artifact.sha256 ?? "none"}`}>
              <TableCell className="max-w-[12rem] truncate font-mono text-2xs" title={artifact.s3_key}>
                {artifact.s3_key}
              </TableCell>
              <TableCell className="max-w-[10rem] truncate font-mono text-2xs" title={artifact.sha256 ?? undefined}>
                {artifact.sha256 ?? "—"}
              </TableCell>
              <TableCell className="text-2xs">{artifact.mime ?? "—"}</TableCell>
              <TableCell className="text-2xs">{artifact.role ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function EvidenceBundleTabs({
  bundle,
  showArtifacts = true,
}: {
  bundle: EvidenceBundle;
  showArtifacts?: boolean;
}) {
  const sections = [
    { id: "http", label: "HTTP", content: bundle.http_transcript, empty: "No HTTP transcript." },
    { id: "terminal", label: "Terminal", content: bundle.terminal_output, empty: "No terminal output." },
    { id: "command", label: "Command", content: bundle.command, empty: "No command recorded." },
    { id: "scanner", label: "Scanner", content: bundle.scanner_output, empty: "No scanner output." },
    { id: "poc", label: "PoC", content: bundle.poc_script, empty: "No PoC script." },
  ].filter((section) => section.content?.trim());

  const hasScreenshots = bundle.screenshots.length > 0;
  const hasArtifacts = showArtifacts && bundle.artifact_refs.length > 0;

  if (sections.length === 0 && !hasScreenshots && !hasArtifacts) {
    return (
      <p className="text-sm text-muted-foreground">
        No structured evidence in this bundle. Attach proof artifacts via the findings API.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <TextEvidenceBlock key={section.id} label={section.label} content={section.content} emptyLabel={section.empty} />
      ))}
      {hasScreenshots ? (
        <div className="space-y-2">
          <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">Screenshots</p>
          <ScreenshotGallery screenshots={bundle.screenshots} />
        </div>
      ) : null}
      {hasArtifacts ? (
        <div className="space-y-2">
          <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">Artifact refs</p>
          <ArtifactRefsTable artifacts={bundle.artifact_refs} />
        </div>
      ) : null}
    </div>
  );
}

export function FindingProofMeta({ finding }: { finding: FindingDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <ProofBadge proof={finding.proof_status} />
      <span className="text-xs text-muted-foreground">
        Last verified{" "}
        {finding.verified_at ? <RelativeTime date={finding.verified_at} className="text-xs" /> : "—"}
      </span>
    </div>
  );
}

export type EvidenceSectionKey =
  | "http_transcript"
  | "terminal_output"
  | "command"
  | "scanner_output"
  | "poc_script"
  | "screenshots"
  | "artifact_refs"
  | "replay_steps"
  | "remediation";

export const EVIDENCE_SECTION_LABELS: Record<EvidenceSectionKey, string> = {
  http_transcript: "HTTP transcript",
  terminal_output: "Terminal output",
  command: "Command",
  scanner_output: "Scanner output",
  poc_script: "PoC script",
  screenshots: "Screenshots",
  artifact_refs: "Artifact refs",
  replay_steps: "Replay steps",
  remediation: "Remediation",
};

export function listEvidenceSections(bundle: EvidenceBundle): EvidenceSectionKey[] {
  const sections: EvidenceSectionKey[] = [];
  if (bundle.http_transcript?.trim()) sections.push("http_transcript");
  if (bundle.terminal_output?.trim()) sections.push("terminal_output");
  if (bundle.command?.trim()) sections.push("command");
  if (bundle.scanner_output?.trim()) sections.push("scanner_output");
  if (bundle.poc_script?.trim()) sections.push("poc_script");
  if (bundle.screenshots.length > 0) sections.push("screenshots");
  if (bundle.artifact_refs.length > 0) sections.push("artifact_refs");
  if (bundle.replay_steps?.trim()) sections.push("replay_steps");
  if (bundle.remediation?.trim()) sections.push("remediation");
  return sections;
}

export function EvidenceSectionPreview({
  section,
  bundle,
}: {
  section: EvidenceSectionKey;
  bundle: EvidenceBundle;
}) {
  switch (section) {
    case "http_transcript":
      return <TextEvidenceBlock label="HTTP transcript" content={bundle.http_transcript} emptyLabel="No HTTP transcript." />;
    case "terminal_output":
      return <TextEvidenceBlock label="Terminal output" content={bundle.terminal_output} emptyLabel="No terminal output." />;
    case "command":
      return <TextEvidenceBlock label="Command" content={bundle.command} emptyLabel="No command." />;
    case "scanner_output":
      return <TextEvidenceBlock label="Scanner output" content={bundle.scanner_output} emptyLabel="No scanner output." />;
    case "poc_script":
      return <TextEvidenceBlock label="PoC script" content={bundle.poc_script} emptyLabel="No PoC script." />;
    case "screenshots":
      return <ScreenshotGallery screenshots={bundle.screenshots} />;
    case "artifact_refs":
      return <ArtifactRefsTable artifacts={bundle.artifact_refs} />;
    case "replay_steps":
      return <TextEvidenceBlock label="Replay steps" content={bundle.replay_steps} emptyLabel="No replay steps." />;
    case "remediation":
      return <TextEvidenceBlock label="Remediation" content={bundle.remediation} emptyLabel="No remediation guidance." />;
    default:
      return null;
  }
}

export function FindingTreeRow({
  finding,
  sectionCount,
  selected,
  onSelect,
}: {
  finding: FindingEvidenceSummary;
  sectionCount: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition-colors",
        selected ? "bg-primary/10 ring-1 ring-primary/30" : "hover:bg-muted/30",
      )}
    >
      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="truncate text-sm font-medium">{finding.title}</p>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <ProofBadge proof={resolveProofStatus(finding)} />
          <span className="text-2xs text-muted-foreground">
            {sectionCount} section{sectionCount === 1 ? "" : "s"}
          </span>
        </div>
      </div>
    </button>
  );
}
