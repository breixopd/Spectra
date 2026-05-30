"""Finding schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from spectra_persistence.finding_evidence import (
    EvidenceArtifactRef,
    EvidenceBundle,
    normalize_evidence_bundle,
    resolve_proof_status,
)

if TYPE_CHECKING:
    from spectra_persistence.models.finding import Finding


class FindingResponse(BaseModel):
    """Schema for finding list/detail base fields."""

    id: str
    title: str
    description: str | None
    severity: str
    status: str
    proof_status: str
    verified_at: str | None = None
    tool_source: str
    target_id: str
    target_address: str
    target_label: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class FindingDetailResponse(FindingResponse):
    """Detailed finding response with evidence fields."""

    cvss_score: float | None = None
    cve_id: str | None = None
    evidence: dict[str, Any] | None = None
    evidence_bundle: EvidenceBundle = Field(default_factory=EvidenceBundle)


def finding_to_response(finding: Finding) -> FindingDetailResponse:
    """Serialize a Finding ORM row to an API response."""
    target = getattr(finding, "target", None)
    target_address = target.address if target is not None else ""
    target_label = (target.description or target.address) if target is not None else ""

    evidence = finding.evidence
    public_evidence = None if evidence is None else {key: value for key, value in evidence.items() if key != "_bundle"}

    return FindingDetailResponse(
        id=finding.id,
        target_id=finding.target_id,
        title=finding.title,
        description=finding.description,
        severity=finding.severity.value,
        status=finding.status.value,
        proof_status=resolve_proof_status(finding.proof_status, finding.status, evidence).value,
        verified_at=finding.verified_at.isoformat() if finding.verified_at else None,
        cvss_score=finding.cvss_score,
        cve_id=finding.cve_id,
        tool_source=finding.tool_source,
        evidence=public_evidence,
        evidence_bundle=normalize_evidence_bundle(evidence),
        target_address=target_address,
        target_label=target_label,
        created_at=finding.created_at.isoformat(),
    )


__all__ = [
    "EvidenceArtifactRef",
    "EvidenceBundle",
    "FindingDetailResponse",
    "FindingResponse",
    "finding_to_response",
]
