"""Unit tests for finding evidence normalization."""

from spectra_persistence.finding_evidence import (
    has_reproducible_evidence,
    initial_proof_status,
    normalize_evidence_bundle,
    prepare_evidence_storage,
    resolve_proof_status,
)
from spectra_persistence.models.finding import FindingStatus, ProofStatus


def test_normalize_evidence_bundle_from_flat_keys():
    bundle = normalize_evidence_bundle(
        {
            "request": "GET /admin HTTP/1.1",
            "response": "HTTP/1.1 200 OK",
            "stdout": "exploit succeeded",
            "command": "python poc.py",
            "screenshot": "s3://bucket/shot.png",
            "scanner_output": '{"template-id":"x"}',
            "poc_script": "print('pwn')",
            "s3_key": "missions/1/evidence/poc.py",
            "sha256": "abc123",
            "kind": "custom_poc",
            "replay_steps": "Run poc.py against /admin",
            "remediation": "Patch input validation",
        }
    )

    assert "GET /admin" in (bundle.http_transcript or "")
    assert bundle.terminal_output == "exploit succeeded"
    assert bundle.command == "python poc.py"
    assert bundle.screenshots == ["s3://bucket/shot.png"]
    assert bundle.scanner_output == '{"template-id":"x"}'
    assert bundle.poc_script == "print('pwn')"
    assert bundle.artifact_refs[0].s3_key == "missions/1/evidence/poc.py"
    assert bundle.replay_steps == "Run poc.py against /admin"
    assert bundle.remediation == "Patch input validation"


def test_prepare_evidence_storage_persists_bundle():
    stored = prepare_evidence_storage({"stdout": "ok", "s3_key": "missions/1/raw.txt"})
    assert stored is not None
    assert stored["stdout"] == "ok"
    assert stored["_bundle"]["terminal_output"] == "ok"
    assert stored["_bundle"]["artifact_refs"][0]["s3_key"] == "missions/1/raw.txt"


def test_initial_proof_status_mapping():
    assert initial_proof_status(FindingStatus.VERIFIED, None) == ProofStatus.VERIFIED
    assert initial_proof_status(FindingStatus.EXPLOITED, None) == ProofStatus.VERIFIED
    assert initial_proof_status(FindingStatus.FALSE_POSITIVE, None) == ProofStatus.NOT_REPRODUCIBLE
    assert initial_proof_status(FindingStatus.RETEST_PENDING, None) == ProofStatus.NEEDS_VERIFICATION
    assert initial_proof_status(FindingStatus.POTENTIAL, {"s3_key": "x"}) == ProofStatus.NEEDS_VERIFICATION
    assert initial_proof_status(FindingStatus.POTENTIAL, {"note": "scanner only"}) == ProofStatus.CANDIDATE


def test_resolve_proof_status_for_legacy_verified_rows():
    resolved = resolve_proof_status(
        ProofStatus.CANDIDATE,
        FindingStatus.VERIFIED,
        {"note": "legacy row"},
    )
    assert resolved == ProofStatus.VERIFIED


def test_has_reproducible_evidence_from_bundle():
    stored = prepare_evidence_storage({"sha256": "abc", "s3_key": "missions/1/x"})
    assert has_reproducible_evidence(stored)
