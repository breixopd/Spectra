"""Small, reviewable GraphQL discovery and access-exposure probe.

This is intentionally a first-party executable rather than an embedded Python
one-liner in plugin JSON.  The surrounding Spectra execution pipeline still
enforces authorization, target scope, and command argument quoting.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

VERSION = "1.1.0"
_GRAPHQL_NAME = re.compile(r"^[_A-Za-z][_0-9A-Za-z]*$")
_INTROSPECTION_QUERY = """
query SpectraIntrospection {
  __schema {
    queryType { name }
    mutationType { name }
    types { name kind fields { name args { name } } }
  }
}
""".strip()


class GraphQLRequestError(RuntimeError):
    """A GraphQL endpoint could not be queried."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Introspect and lightly probe a GraphQL endpoint.")
    parser.add_argument("target", help="Absolute http(s) GraphQL endpoint URL")
    parser.add_argument("--introspect", action="store_true", help="Print schema query and mutation names.")
    parser.add_argument("--authz", action="store_true", help="Probe zero-argument query fields for anonymous exposure.")
    parser.add_argument("--all", action="store_true", help="Run introspection and zero-argument field probes.")
    parser.add_argument("--field-wordlist", type=Path, help="Optional newline-separated query field candidates.")
    parser.add_argument(
        "--header", action="append", default=[], help="Request header in 'Name: value' form; repeatable."
    )
    parser.add_argument("--max-operations", type=int, default=20, help="Maximum field probes (1-100).")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (0.1-60).")
    parser.add_argument("--version", action="version", version=f"graphql-fuzzer {VERSION}")
    return parser


def _validate_target(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("target must be an absolute http(s) URL without credentials or a fragment")
    return value


def _parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        name, separator, header_value = value.partition(":")
        if not separator or not name.strip() or "\r" in value or "\n" in value:
            raise ValueError("headers must use 'Name: value' format without control characters")
        headers[name.strip()] = header_value.strip()
    return headers


def _post_graphql(target: str, query: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    body = json.dumps({"query": query}).encode("utf-8")
    request_headers = {"Accept": "application/json", "Content-Type": "application/json", **headers}
    request = Request(target, data=body, headers=request_headers, method="POST")  # noqa: S310 - validated authorized target
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - the authorized target is validated upstream
            payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")[:500]
        raise GraphQLRequestError(f"HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise GraphQLRequestError(str(exc.reason)) from exc

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GraphQLRequestError("endpoint returned non-JSON content") from exc
    if not isinstance(result, dict):
        raise GraphQLRequestError("endpoint returned a non-object GraphQL response")
    return result


def _root_fields(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    schema = payload.get("data", {}).get("__schema", {})
    if not isinstance(schema, dict):
        return [], []
    types = {item.get("name"): item for item in schema.get("types", []) if isinstance(item, dict)}
    query_type = schema.get("queryType", {})
    mutation_type = schema.get("mutationType", {})
    query_name = query_type.get("name") if isinstance(query_type, dict) else None
    mutation_name = mutation_type.get("name") if isinstance(mutation_type, dict) else None
    fields = types.get(query_name, {}).get("fields", []) if query_name else []
    mutations = types.get(mutation_name, {}).get("fields", []) if mutation_name else []
    return [item for item in fields if isinstance(item, dict)], [
        str(item.get("name")) for item in mutations if isinstance(item, dict) and item.get("name")
    ]


def _candidate_fields(fields: list[dict[str, Any]], wordlist: Path | None, limit: int) -> list[str]:
    candidates = [
        str(field["name"])
        for field in fields
        if isinstance(field.get("name"), str) and _GRAPHQL_NAME.fullmatch(str(field["name"])) and not field.get("args")
    ]
    if wordlist:
        try:
            candidates.extend(
                line.strip()
                for line in wordlist.read_text(encoding="utf-8").splitlines()
                if _GRAPHQL_NAME.fullmatch(line.strip())
            )
        except OSError as exc:
            raise ValueError(f"unable to read field wordlist: {exc}") from exc
    return list(dict.fromkeys(candidates))[:limit]


def _probe_query(field: str) -> str:
    return f"query SpectraProbe {{ {field} }}"


def run(args: argparse.Namespace) -> int:
    target = _validate_target(args.target)
    if not 0.1 <= args.timeout <= 60:
        raise ValueError("timeout must be between 0.1 and 60 seconds")
    if not 1 <= args.max_operations <= 100:
        raise ValueError("max-operations must be between 1 and 100")
    headers = _parse_headers(args.header)
    introspection = _post_graphql(target, _INTROSPECTION_QUERY, headers, args.timeout)
    if introspection.get("errors"):
        print(json.dumps({"errors": introspection["errors"]}, sort_keys=True), file=sys.stderr)
        return 1

    fields, mutations = _root_fields(introspection)
    print(f"[+] Found {len(fields)} fields")
    if args.introspect or args.all or not args.authz:
        for field in fields:
            if isinstance(field.get("name"), str):
                print(f"[+] Query field: {field['name']}")
        for mutation in mutations:
            print(f"mutation {{ {mutation} }}")

    if args.authz or args.all or args.field_wordlist:
        for field in _candidate_fields(fields, args.field_wordlist, args.max_operations):
            response = _post_graphql(target, _probe_query(field), headers, args.timeout)
            if response.get("data") and not response.get("errors"):
                print(f"[!] Possible authorization exposure for {field}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        return run(parser.parse_args(argv))
    except (GraphQLRequestError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover - console-script entry point
    raise SystemExit(main())
