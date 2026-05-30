"""Tests for pentest framework phase timeline helpers (dynamic framework-driven)."""

from spectra_mission.framework_progress import (
    framework_display_name,
    framework_phase_timeline,
    normalize_pentest_framework,
)


def test_normalize_unknown_defaults_to_ptes() -> None:
    assert normalize_pentest_framework("not-a-real-framework") == "ptes"
    assert normalize_pentest_framework("owasp") == "owasp"
    assert normalize_pentest_framework("nist") == "nist"


def test_framework_display_name() -> None:
    assert "OWASP" in framework_display_name("owasp")
    assert "PTES" in framework_display_name("ptes")
    assert "NIST" in framework_display_name("nist")


def test_timeline_completed_all_done() -> None:
    tl = framework_phase_timeline(
        current_phase="reporting",
        mission_status="completed",
        pentest_framework="ptes",
    )
    # PTES has 7 operational phases (excluding terminal "complete")
    assert len(tl) == 7
    assert all(s["done"] for s in tl)
    assert not any(s["current"] for s in tl)


def test_timeline_running_current_step() -> None:
    tl = framework_phase_timeline(
        current_phase="enumeration",
        mission_status="running",
        pentest_framework="ptes",
    )
    current = [s for s in tl if s["current"]]
    assert len(current) == 1
    assert current[0]["id"] == "enumeration"
    done_ids = {s["id"] for s in tl if s["done"]}
    assert "scope" in done_ids
    assert "discovery" in done_ids
