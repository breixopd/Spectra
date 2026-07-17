"""Evidence bundle normalization for findings."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from spectra_persistence.models.finding import FindingStatus, ProofStatus

_HTTP_TRANSCRIPT_KEYS = (
    "http_transcript",
    "request_response",
    "request",
    "response",
    "curl_output",
    "matched-at",
)
_TERMINAL_OUTPUT_KEYS = ("terminal_output", "stdout", "stderr", "output", "proof")
_COMMAND_KEYS = ("command", "cmd", "tool_command", "executed_command")
_SCREENSHOT_KEYS = ("screenshot", "screenshots")
_SCANNER_OUTPUT_KEYS = (
    "scanner_output",
    "nuclei_output",
    "template_output",
    "scan_output",
    "matched-line",
)
_POC_SCRIPT_KEYS = ("poc_script", "exploit_script", "script", "payload")
_REPLAY_KEYS = ("replay_steps", "steps", "reproduction", "replay")
_REMEDIATION_KEYS = ("remediation", "recommendation", "fix")
_ARTIFACT_KEYS = ("s3_key", "sha256", "artifact_id", "mime", "mime_type", "kind", "role")


class EvidenceArtifactRef(BaseModel):
    """Reference to a stored evidence artifact."""

    s3_key: str
    sha256: str | None = None
    mime: str | None = None
    role: str | None = None

    model_config = ConfigDict(extra="forbid")


class EvidenceBundle(BaseModel):
    """Normalized evidence sections for a finding."""

    http_transcript: str | None = None
    terminal_output: str | None = None
    command: str | None = None
    screenshots: list[str] = Field(default_factory=list)
    scanner_output: str | None = None
    poc_script: str | None = None
    artifact_refs: list[EvidenceArtifactRef] = Field(default_factory=list)
    replay_steps: str | None = None
    remediation: str | None = None

    model_config = ConfigDict(extra="forbid")


def _first_string(evidence: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _combine_http_transcript(evidence: dict[str, Any]) -> str | None:
    direct = _first_string(evidence, _HTTP_TRANSCRIPT_KEYS)
    if direct:
        return direct
    request = evidence.get("request")
    response = evidence.get("response")
    if isinstance(request, str) and isinstance(response, str):
        return f"--- request ---\n{request}\n\n--- response ---\n{response}"
    if isinstance(request, str):
        return request
    if isinstance(response, str):
        return response
    return None


def _parse_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, str) and item.strip()]
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _artifact_refs_from_evidence(evidence: dict[str, Any]) -> list[EvidenceArtifactRef]:
    refs: list[EvidenceArtifactRef] = []

    raw_refs = evidence.get("artifact_refs")
    if isinstance(raw_refs, list):
        for item in raw_refs:
            if isinstance(item, dict) and item.get("s3_key"):
                refs.append(
                    EvidenceArtifactRef(
                        s3_key=str(item["s3_key"]),
                        sha256=str(item["sha256"]) if item.get("sha256") else None,
                        mime=str(item.get("mime") or item.get("mime_type"))
                        if item.get("mime") or item.get("mime_type")
                        else None,
                        role=str(item.get("role") or item.get("kind"))
                        if item.get("role") or item.get("kind")
                        else None,
                    )
                )
        if refs:
            return refs

    if evidence.get("s3_key"):
        refs.append(
            EvidenceArtifactRef(
                s3_key=str(evidence["s3_key"]),
                sha256=str(evidence["sha256"]) if evidence.get("sha256") else None,
                mime=str(evidence.get("mime") or evidence.get("mime_type"))
                if evidence.get("mime") or evidence.get("mime_type")
                else None,
                role=str(evidence.get("role") or evidence.get("kind"))
                if evidence.get("role") or evidence.get("kind")
                else None,
            )
        )
    return refs


def normalize_evidence_bundle(evidence: dict[str, Any] | None) -> EvidenceBundle:
    """Build a typed evidence bundle from stored finding evidence."""
    if not evidence:
        return EvidenceBundle()

    stored = evidence.get("_bundle")
    if isinstance(stored, dict):
        return EvidenceBundle.model_validate(stored)

    screenshots: list[str] = []
    for key in _SCREENSHOT_KEYS:
        screenshots.extend(_parse_string_list(evidence.get(key)))

    return EvidenceBundle(
        http_transcript=_combine_http_transcript(evidence),
        terminal_output=_first_string(evidence, _TERMINAL_OUTPUT_KEYS),
        command=_first_string(evidence, _COMMAND_KEYS),
        screenshots=screenshots,
        scanner_output=_first_string(evidence, _SCANNER_OUTPUT_KEYS),
        poc_script=_first_string(evidence, _POC_SCRIPT_KEYS),
        artifact_refs=_artifact_refs_from_evidence(evidence),
        replay_steps=_first_string(evidence, _REPLAY_KEYS),
        remediation=_first_string(evidence, _REMEDIATION_KEYS),
    )


def has_reproducible_evidence(evidence: dict[str, Any] | None) -> bool:
    """Return True when evidence includes durable artifact references."""
    if not evidence:
        return False

    bundle = normalize_evidence_bundle(evidence)
    if bundle.artifact_refs:
        return True

    for key in ("artifact_id", "tool_execution_id", "s3_key", "sha256"):
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def prepare_evidence_storage(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize incoming flat evidence and persist a structured bundle alongside raw keys."""
    if not evidence:
        return None

    stored = dict(evidence)
    stored["_bundle"] = normalize_evidence_bundle(stored).model_dump(mode="json")
    return stored


def initial_proof_status(
    status: FindingStatus,
    evidence: dict[str, Any] | None,
) -> ProofStatus:
    """Derive the initial proof status for a newly created finding."""
    if status in {FindingStatus.VERIFIED, FindingStatus.EXPLOITED}:
        return ProofStatus.VERIFIED
    if status == FindingStatus.FALSE_POSITIVE:
        return ProofStatus.NOT_REPRODUCIBLE
    if status == FindingStatus.RETEST_PENDING:
        return ProofStatus.NEEDS_VERIFICATION
    if has_reproducible_evidence(evidence):
        return ProofStatus.NEEDS_VERIFICATION
    return ProofStatus.CANDIDATE


def proof_status_for_status_change(
    new_status: FindingStatus,
    *,
    current: ProofStatus,
) -> ProofStatus:
    """Map workflow status transitions onto proof status."""
    if new_status in {FindingStatus.VERIFIED, FindingStatus.EXPLOITED}:
        return ProofStatus.VERIFIED
    if new_status == FindingStatus.FALSE_POSITIVE:
        return ProofStatus.NOT_REPRODUCIBLE
    if new_status == FindingStatus.RETEST_PENDING:
        return ProofStatus.NEEDS_VERIFICATION
    return current


def resolve_proof_status(
    stored: ProofStatus,
    status: FindingStatus,
    evidence: dict[str, Any] | None,
) -> ProofStatus:
    """Resolve proof status for API responses, including legacy rows."""
    if stored != ProofStatus.CANDIDATE:
        return stored
    return initial_proof_status(status, evidence)
