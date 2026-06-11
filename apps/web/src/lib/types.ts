/** API-aligned domain types for the Spectra SPA. */

export interface FindingsListParams {
  page?: number;
  per_page?: number;
  severity?: FindingSeverity;
  status?: FindingStatus;
  proof_status?: ProofStatus;
}

export interface MissionsListParams {
  page?: number;
  per_page?: number;
  status?: string;
  target?: string;
  search?: string;
  sort_by?: "created_at" | "status" | "target";
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export type FindingSeverity = "critical" | "high" | "medium" | "low" | "info";

export type FindingStatus =
  | "potential"
  | "verified"
  | "exploited"
  | "false_positive"
  | "dismissed"
  | "retest_pending";

export type ProofStatus = "candidate" | "needs_verification" | "verified" | "not_reproducible";

export interface ArtifactRef {
  s3_key: string;
  sha256: string | null;
  mime: string | null;
  role: string | null;
}

export interface EvidenceBundle {
  http_transcript: string | null;
  terminal_output: string | null;
  command: string | null;
  screenshots: string[];
  scanner_output: string | null;
  poc_script: string | null;
  artifact_refs: ArtifactRef[];
  replay_steps: string | null;
  remediation: string | null;
}

export interface Finding {
  id: string;
  title: string;
  description: string | null;
  severity: FindingSeverity;
  status: FindingStatus;
  proof_status: ProofStatus;
  verified_at: string | null;
  tool_source: string;
  target_id: string;
  target_address: string;
  target_label: string;
  created_at: string;
}

export interface FindingDetail extends Finding {
  cvss_score: number | null;
  cve_id: string | null;
  evidence: Record<string, unknown> | null;
  evidence_bundle?: EvidenceBundle | null;
}

export interface FindingUpdateRequest {
  title?: string;
  description?: string | null;
  severity?: FindingSeverity;
  status?: FindingStatus;
  cvss_score?: number | null;
  cve_id?: string | null;
}

export interface ToolExecutionRecord {
  tool: string;
  args: Record<string, unknown>;
  command: string | null;
  success: boolean;
  error: string | null;
  timestamp: string;
}

export interface FrameworkPhaseTimelineEntry {
  id: string;
  label: string;
  description?: string;
  done: boolean;
  current: boolean;
}

export interface AttackSurfaceSummary {
  hosts?: number;
  services?: number;
  vulnerabilities?: number;
  [key: string]: unknown;
}

export interface Mission {
  id: string;
  target: string;
  status: string;
  current_phase: string | null;
  logs: string[];
  directive: string | null;
  findings: Record<string, unknown>[] | null;
  findings_count: number | null;
  tools_run: string[];
  tool_executions: ToolExecutionRecord[] | null;
  report_path: string | null;
  attack_surface: AttackSurfaceSummary | null;
  pentest_framework: string;
  framework_label: string;
  framework_phase_timeline: FrameworkPhaseTimelineEntry[];
  demo_url: string | null;
}

export interface MissionProgress {
  percent: number;
  phase: string;
  eta_minutes?: number | null;
  completed_tasks?: number;
  total_tasks?: number;
  active_tasks?: Array<Record<string, string>>;
}

export interface MissionSummaryFindingCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
  total: number;
}

export interface MissionSummaryItem {
  id: string;
  target: string;
  directive: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  findings: MissionSummaryFindingCounts;
}

export interface MissionsSummaryResponse {
  missions: MissionSummaryItem[];
  totals: MissionSummaryFindingCounts;
  count: number;
  total: number;
  skip: number;
  limit: number;
}

export interface StartMissionRequest {
  target: string;
  directive?: string;
  requirements?: string | null;
  record_demo?: boolean;
  requires_approval?: boolean | null;
  scan_mode?: "autonomous" | "guided" | "manual" | null;
  playbook_id?: string | null;
  authorization_confirmed: boolean;
  vpn_config?: string | null;
  pentest_framework?: string;
  roe?: Record<string, unknown> | null;
  training_opt_in?: boolean;
}

export interface ComponentStatus {
  status: string;
  message: string | null;
  details?: Record<string, unknown> | null;
}

export interface ToolStats {
  total: number;
  ready: number;
  installing: number;
  pending: number;
  failed: number;
  disabled: number;
}

export interface OngoingOperation {
  id: string;
  type: string;
  description: string;
  started_at: string | null;
  progress: number | null;
  details?: Record<string, unknown> | null;
}

export interface SystemStatus {
  status: string;
  message: string;
  timestamp: string;
  database: ComponentStatus;
  cache: ComponentStatus;
  tools_installing: boolean;
  embeddings_loading: boolean;
  tool_stats: ToolStats;
  operations: OngoingOperation[];
  setup_complete: boolean;
  setup_message: string | null;
  rag_status: string;
  tool_cache_stats: Record<string, number> | null;
  storage_health: Record<string, unknown> | null;
}

export interface ToolSummary {
  id: string;
  name: string;
  version: string;
  category: string;
  description: string;
  status: string;
  enabled: boolean;
  icon: string;
  color: string;
}

export interface ToolListResponse {
  tools: ToolSummary[];
  total: number;
}

export interface MissionEventPayload {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
  source?: string;
}

/** Active mission statuses for Mission Control filtering. */
export const ACTIVE_MISSION_STATUSES = [
  "created",
  "initializing",
  "scoping",
  "planning",
  "running",
  "scanning",
  "analyzing",
  "executing",
  "exploiting",
  "reporting",
  "paused",
  "stopping",
] as const;

type ProofStatusInput = Partial<Pick<Finding, "proof_status">> &
  Pick<Finding, "status"> & { evidence?: Record<string, unknown> | null };

/** Prefer authoritative server proof_status; fall back to legacy derivation. */
export function resolveProofStatus(finding: ProofStatusInput): ProofStatus {
  return finding.proof_status ?? deriveProofStatus(finding);
}

export function deriveProofStatus(
  finding: Pick<Finding, "status"> & { evidence?: Record<string, unknown> | null },
): ProofStatus {
  switch (finding.status) {
    case "verified":
    case "exploited":
      return "verified";
    case "false_positive":
    case "dismissed":
      return "not_reproducible";
    case "retest_pending":
      return "needs_verification";
    default: {
      const evidence = finding.evidence;
      if (evidence) {
        const keys = ["artifact_id", "tool_execution_id", "s3_key", "sha256"];
        if (keys.some((key) => Boolean(evidence[key]))) {
          return "candidate";
        }
      }
      return "candidate";
    }
  }
}

export const EMPTY_EVIDENCE_BUNDLE: EvidenceBundle = {
  http_transcript: null,
  terminal_output: null,
  command: null,
  screenshots: [],
  scanner_output: null,
  poc_script: null,
  artifact_refs: [],
  replay_steps: null,
  remediation: null,
};

export function normalizeEvidenceBundle(bundle: EvidenceBundle | null | undefined): EvidenceBundle {
  if (!bundle) {
    return EMPTY_EVIDENCE_BUNDLE;
  }
  return {
    ...EMPTY_EVIDENCE_BUNDLE,
    ...bundle,
    screenshots: bundle.screenshots ?? [],
    artifact_refs: bundle.artifact_refs ?? [],
  };
}

export function evidenceBundleHasContent(bundle: EvidenceBundle): boolean {
  return (
    Boolean(bundle.http_transcript) ||
    Boolean(bundle.terminal_output) ||
    Boolean(bundle.command) ||
    Boolean(bundle.scanner_output) ||
    Boolean(bundle.poc_script) ||
    Boolean(bundle.replay_steps) ||
    Boolean(bundle.remediation) ||
    bundle.screenshots.length > 0 ||
    bundle.artifact_refs.length > 0
  );
}

export function deriveExploitability(
  finding: Pick<Finding, "status"> & { cvss_score?: number | null },
): string {
  if (finding.status === "exploited") {
    return "Confirmed";
  }
  if (finding.status === "verified") {
    return "Verified";
  }
  const score = finding.cvss_score;
  if (score != null && score >= 7) {
    return "Likely";
  }
  if (score != null && score >= 4) {
    return "Possible";
  }
  return "Unknown";
}

export const SEVERITY_ORDER: Record<FindingSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

export const PROOF_ORDER: Record<ProofStatus, number> = {
  verified: 0,
  needs_verification: 1,
  candidate: 2,
  not_reproducible: 3,
};

export interface MissionFindingSummary {
  id: string;
  title: string;
  severity: FindingSeverity | string;
  status: FindingStatus | string;
  description: string;
  tool_source: string;
  created_at: string;
}

export interface TaskTreeUITask {
  id: string;
  name: string;
  tool: string | null;
  status: string;
  children: TaskTreeUITask[];
}

export interface TaskTreeNode {
  id: string;
  name: string;
  technique: string;
  status: string;
  parent_id: string | null;
  children: string[];
  findings: string[];
  tool_used: string | null;
  started_at: number | null;
  completed_at: number | null;
  details: Record<string, unknown>;
}

export interface MissionTaskTree {
  mission_id: string;
  nodes: Record<string, TaskTreeNode>;
  tasks: TaskTreeUITask[];
}

export interface MissionArtifact {
  id: string;
  filename: string;
  kind: string;
  key: string;
  size: number;
  sha256: string;
  created_at: string;
  expires_at: string | null;
  labels: string[];
}

export interface StatusResponse {
  message: string;
}

export interface UserSettings {
  llm_api_key_configured: boolean;
  llm_api_base_url: string | null;
  llm_model: string | null;
  embedding_api_key_configured: boolean;
  embedding_api_base_url: string | null;
  embedding_model: string | null;
  email_notifications: boolean;
  webhook_url: string | null;
  notify_on_mission_complete: boolean;
  notify_on_critical_finding: boolean;
  prefer_mission_approval: boolean;
  default_scan_mode: string;
  default_report_format: string;
  timezone: string;
  share_training_data: boolean;
}

export interface UserSettingsUpdate {
  email_notifications?: boolean;
  webhook_url?: string | null;
  notify_on_mission_complete?: boolean;
  notify_on_critical_finding?: boolean;
  prefer_mission_approval?: boolean;
  default_scan_mode?: "autonomous" | "guided" | "manual";
  default_report_format?: "pdf" | "html" | "json";
  timezone?: string;
  share_training_data?: boolean;
  llm_api_key?: string | null;
  llm_api_base_url?: string | null;
  llm_model?: string | null;
  embedding_api_key?: string | null;
  embedding_api_base_url?: string | null;
  embedding_model?: string | null;
}

export interface ApiKeySummary {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  key: string;
  prefix: string;
}

export type AttackGraphNodeKind =
  | "entry_point"
  | "service"
  | "credential"
  | "pivot"
  | "exploit"
  | "finding"
  | "task";

export const COMPLETED_MISSION_STATUSES = [
  "completed",
  "exploitation_successful",
  "failed",
  "stopped",
  "cancelled",
] as const;
