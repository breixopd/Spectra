"""Tests for the mission summary output-model helpers."""

from unittest.mock import MagicMock

from app.services.mission.output_model import (
    get_mission_finding_counts,
    get_mission_findings,
    get_reporter_findings,
)


def test_get_mission_findings_returns_empty_list_for_missing_summary():
    mission = MagicMock()
    mission.summary = None

    assert get_mission_findings(mission) == []
    assert get_mission_findings({}) == []


def test_get_mission_findings_prefers_explicit_empty_top_level_list_over_summary():
    mission = {
        "findings": [],
        "summary": {
            "findings": [
                {"title": "stale"},
            ]
        },
    }

    assert get_mission_findings(mission) == []


def test_get_mission_finding_counts_aggregates_normalized_severities():
    summary = {
        "findings": [
            {"severity": "CRITICAL"},
            {"severity": "high"},
            {"severity": "High"},
            {"severity": None},
            {},
            {"severity": "unknown"},
            "not-a-dict",
        ]
    }

    assert get_mission_finding_counts(summary) == {
        "critical": 1,
        "high": 2,
        "medium": 0,
        "low": 0,
        "info": 3,
        "total": 6,
    }


def test_get_reporter_findings_maps_fields_safely():
    summary = {
        "findings": [
            {
                "title": "SQL Injection",
                "severity": "critical",
                "description": "Unsanitized query parameter",
                "tool": "sqlmap",
                "confirmed": True,
            },
            {
                "title": "Missing Header",
                "severity": None,
                "tool_source": "nuclei",
            },
        ]
    }

    assert get_reporter_findings(summary) == [
        {
            "title": "SQL Injection",
            "severity": "critical",
            "description": "Unsanitized query parameter",
            "source": "sqlmap",
            "confirmed": True,
            "tool_name": "sqlmap",
        },
        {
            "title": "Missing Header",
            "severity": "info",
            "description": "",
            "source": "nuclei",
            "confirmed": False,
            "tool_name": "nuclei",
        },
    ]


def test_get_reporter_findings_normalizes_unknown_severity_to_info():
    summary = {
        "findings": [
            {
                "title": "Weird Severity",
                "severity": "unexpected",
            },
        ]
    }

    assert get_reporter_findings(summary) == [
        {
            "title": "Weird Severity",
            "severity": "info",
            "description": "",
            "source": "",
            "confirmed": False,
            "tool_name": "",
        }
    ]
