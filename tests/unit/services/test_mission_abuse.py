"""Tests for mission abuse-prevention checks."""

from app.services.compliance.mission_abuse import evaluate_mission_abuse


def test_blocks_broad_public_cidr_even_with_authorization():
    decision = evaluate_mission_abuse(
        target="8.8.0.0/16",
        directive="Perform a normal assessment",
        requirements=None,
        authorization_confirmed=True,
        requires_approval=True,
    )

    assert decision.allowed is False
    assert decision.requires_review is True
    assert any("broad public network" in reason for reason in decision.reasons)


def test_high_risk_terms_require_approval():
    decision = evaluate_mission_abuse(
        target="example.com",
        directive="Attempt a reverse shell if exploitable",
        requirements=None,
        authorization_confirmed=True,
        requires_approval=False,
    )

    assert decision.allowed is False
    assert decision.requires_review is True
    assert decision.risk_score >= 30


def test_high_risk_terms_allowed_when_human_approval_required():
    decision = evaluate_mission_abuse(
        target="example.com",
        directive="Attempt a reverse shell if exploitable",
        requirements=None,
        authorization_confirmed=True,
        requires_approval=True,
    )

    assert decision.allowed is True
    assert decision.requires_review is True


def test_private_lab_cidr_allowed_with_authorization():
    decision = evaluate_mission_abuse(
        target="10.10.0.0/16",
        directive="Perform a normal assessment",
        requirements=None,
        authorization_confirmed=True,
        requires_approval=False,
    )

    assert decision.allowed is True
    assert decision.risk_score == 0
