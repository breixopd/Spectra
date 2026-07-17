"""Regression tests for the first-party plugin executables."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectra_tools.builtin_tools import graphql_fuzzer, imds_fetcher

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_imds_custom_endpoint_is_limited_to_known_metadata_hosts() -> None:
    assert imds_fetcher._normalise_endpoint("http://169.254.169.254/latest/") == "http://169.254.169.254/latest"
    with pytest.raises(ValueError, match="recognized metadata host"):
        imds_fetcher._normalise_endpoint("http://example.com/latest")


def test_imds_rejects_an_ambiguous_custom_endpoint() -> None:
    parser = imds_fetcher._build_parser()
    with pytest.raises(ValueError, match="explicit --provider"):
        imds_fetcher.run(parser.parse_args(["--endpoint", "http://169.254.169.254/latest"]))


def test_graphql_rejects_unsafe_target_and_header_syntax() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        graphql_fuzzer._validate_target("file:///etc/passwd")
    with pytest.raises(ValueError, match="headers must"):
        graphql_fuzzer._parse_headers(["Authorization\nInjected: value"])


def test_graphql_scan_reports_schema_and_bounded_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def fake_post(_target: str, query: str, _headers: dict[str, str], _timeout: float) -> dict[str, object]:
        calls.append(query)
        if "SpectraIntrospection" in query:
            return {
                "data": {
                    "__schema": {
                        "queryType": {"name": "Query"},
                        "mutationType": {"name": "Mutation"},
                        "types": [
                            {
                                "name": "Query",
                                "fields": [
                                    {"name": "public", "args": []},
                                    {"name": "needsArg", "args": [{"name": "id"}]},
                                ],
                            },
                            {"name": "Mutation", "fields": [{"name": "updateThing", "args": []}]},
                        ],
                    }
                }
            }
        return {"data": {"public": "ok"}}

    monkeypatch.setattr(graphql_fuzzer, "_post_graphql", fake_post)
    args = graphql_fuzzer._build_parser().parse_args(
        ["https://api.example.test/graphql", "--all", "--max-operations", "1"]
    )

    assert graphql_fuzzer.run(args) == 0
    output = capsys.readouterr().out
    assert "[+] Found 2 fields" in output
    assert "mutation { updateThing }" in output
    assert "Possible authorization exposure for public" in output
    assert len(calls) == 2


def test_builtin_plugin_manifests_use_first_party_executables() -> None:
    for tool_id in ("imds-fetcher", "graphql-fuzzer"):
        plugin = json.loads((REPOSITORY_ROOT / "plugins" / f"{tool_id}.json").read_text())
        installation = plugin["installation"]
        assert installation["method"] == "none"
        assert installation["verification_command"] == f"{tool_id} --version"
        assert "python3 -c" not in json.dumps(plugin)
