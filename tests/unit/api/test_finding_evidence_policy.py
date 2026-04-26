import pytest
from pydantic import ValidationError

from app.api.routers.findings.core import FindingCreate
from app.models.finding import FindingStatus, Severity


def _finding_payload(**overrides):
    payload = {
        "target_id": "target-1",
        "title": "Remote code execution",
        "description": "Confirmed exploit path",
        "severity": Severity.HIGH,
        "status": FindingStatus.POTENTIAL,
        "tool_source": "nmap",
    }
    payload.update(overrides)
    return payload


def test_high_severity_finding_requires_reproducible_evidence():
    with pytest.raises(ValidationError, match="require artifact_id"):
        FindingCreate(**_finding_payload(evidence={"note": "scanner output only"}))


def test_high_severity_finding_accepts_artifact_evidence():
    finding = FindingCreate(**_finding_payload(evidence={"artifact_id": "artifact-123", "sha256": "abc"}))

    assert finding.severity == Severity.HIGH
