"""Tests for pentest framework phase timeline helpers."""

from spectra_platform.services.mission.framework_progress import (
    framework_display_name,
    framework_phase_timeline,
    normalize_pentest_framework,
)


def test_normalize_unknown_defaults_to_ptes() -> None:
    assert normalize_pentest_framework("not-a-real-framework") == "ptes"
    assert normalize_pentest_framework("owasp_top10_2021") == "owasp_top10_2021"


def test_framework_display_name() -> None:
    assert "OWASP" in framework_display_name("owasp_top10_2021")
    assert framework_display_name("ptes")


def test_timeline_completed_all_done() -> None:
    tl = framework_phase_timeline(
        current_phase="reporting",
        mission_status="completed",
        pentest_framework="ptes",
    )
    assert len(tl) == 7
    assert all(s["done"] for s in tl)
    assert not any(s["current"] for s in tl)


def test_timeline_running_current_step() -> None:
    tl = framework_phase_timeline(
        current_phase="enumeration",
        mission_status="running",
        pentest_framework="network_pentest",
    )
    current = [s for s in tl if s["current"]]
    assert len(current) == 1
    assert current[0]["id"] == "enumeration"
    done_ids = {s["id"] for s in tl if s["done"]}
    assert "scope" in done_ids
    assert "discovery" in done_ids
