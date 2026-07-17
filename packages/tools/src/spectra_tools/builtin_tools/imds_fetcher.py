"""Query a local cloud instance metadata service without shell snippets.

The tool intentionally limits custom endpoints to the three well-known cloud
metadata hosts.  It runs in the approved tools worker and is invoked only
through Spectra's normal scope and capability checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

VERSION = "1.1.0"

_AWS_METADATA_BASE = "http://169.254.169.254/latest"
_GCP_METADATA_BASE = "http://metadata.google.internal/computeMetadata/v1"
_AZURE_METADATA_BASE = "http://169.254.169.254/metadata/instance"
_METADATA_HOSTS = frozenset({"169.254.169.254", "metadata.google.internal"})


class MetadataRequestError(RuntimeError):
    """A metadata service did not accept a request."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AWS, GCP, or Azure instance metadata.")
    parser.add_argument("--provider", choices=("auto", "aws", "gcp", "azure"), default="auto")
    parser.add_argument("--endpoint", help="Override the metadata base URL for a known metadata host.")
    parser.add_argument("--imdsv2", action="store_true", help="Require AWS IMDSv2 rather than falling back to v1.")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-request timeout in seconds (0.1-10).")
    parser.add_argument("--version", action="version", version=f"imds-fetcher {VERSION}")
    return parser


def _validated_timeout(value: float) -> float:
    if not 0.1 <= value <= 10:
        raise ValueError("timeout must be between 0.1 and 10 seconds")
    return value


def _normalise_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or hostname not in _METADATA_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("endpoint must be an http URL for a recognized metadata host")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


def _join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _request_text(
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> str:
    request = Request(url, headers=headers or {}, method=method)  # noqa: S310 - approved metadata endpoint
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - approved metadata endpoint
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise MetadataRequestError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise MetadataRequestError(str(exc.reason)) from exc


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip()


def _query_aws(base: str, timeout: float, require_v2: bool) -> bool:
    token = ""
    try:
        token = _request_text(
            _join(base, "api/token"),
            timeout=timeout,
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        ).strip()
    except MetadataRequestError:
        if require_v2:
            raise

    headers = {"X-aws-ec2-metadata-token": token} if token else {}
    instance_id = _request_text(_join(base, "meta-data/instance-id"), timeout=timeout, headers=headers).strip()
    print("[+] AWS detected")
    print(f"[+] Instance ID: {instance_id}")

    try:
        role = _request_text(
            _join(base, "meta-data/iam/security-credentials/"), timeout=timeout, headers=headers
        ).strip()
        credentials = _json_or_text(
            _request_text(_join(base, f"meta-data/iam/security-credentials/{role}"), timeout=timeout, headers=headers)
        )
        print(f"[+] AWS IAM role: {role}")
        if isinstance(credentials, dict) and credentials.get("AccessKeyId"):
            print(f"[+] AWS Access Key ID: {credentials['AccessKeyId']}")
        print(json.dumps({"provider": "aws", "credentials": credentials}, sort_keys=True))
    except MetadataRequestError:
        print("[*] No AWS IAM role credentials were exposed")
    return True


def _query_gcp(base: str, timeout: float) -> bool:
    headers = {"Metadata-Flavor": "Google"}
    project = _request_text(_join(base, "project/project-id"), timeout=timeout, headers=headers).strip()
    instance_id = _request_text(_join(base, "instance/id"), timeout=timeout, headers=headers).strip()
    print("[+] GCP detected")
    print(f"[+] Project: {project}")
    print(f"[+] Instance ID: {instance_id}")

    try:
        token = _json_or_text(
            _request_text(_join(base, "instance/service-accounts/default/token"), timeout=timeout, headers=headers)
        )
        print("[+] Service Account Token: retrieved")
        print(json.dumps({"provider": "gcp", "token": token}, sort_keys=True))
    except MetadataRequestError:
        print("[*] No GCP service-account token was exposed")
    return True


def _query_azure(base: str, timeout: float) -> bool:
    separator = "&" if "?" in base else "?"
    endpoint = f"{base}{separator}api-version=2021-02-01"
    payload = _json_or_text(_request_text(endpoint, timeout=timeout, headers={"Metadata": "true"}))
    print("[+] Azure detected")
    print(json.dumps({"provider": "azure", "metadata": payload}, sort_keys=True))
    return True


def _provider_attempts(provider: str) -> Iterable[str]:
    return (provider,) if provider != "auto" else ("aws", "gcp", "azure")


def run(args: argparse.Namespace) -> int:
    timeout = _validated_timeout(args.timeout)
    if args.endpoint and args.provider == "auto":
        raise ValueError("--endpoint requires an explicit --provider")

    custom_endpoint = _normalise_endpoint(args.endpoint) if args.endpoint else None
    for provider in _provider_attempts(args.provider):
        base = (
            custom_endpoint
            or {
                "aws": _AWS_METADATA_BASE,
                "gcp": _GCP_METADATA_BASE,
                "azure": _AZURE_METADATA_BASE,
            }[provider]
        )
        try:
            if provider == "aws":
                _query_aws(base, timeout, args.imdsv2)
            elif provider == "gcp":
                _query_gcp(base, timeout)
            else:
                _query_azure(base, timeout)
            return 0
        except MetadataRequestError as exc:
            if args.provider != "auto":
                print(f"[!] {provider.upper()} metadata query failed: {exc}", file=sys.stderr)

    if args.provider == "auto":
        print("[*] No reachable AWS, GCP, or Azure metadata service detected")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        return run(parser.parse_args(argv))
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover - console-script entry point
    raise SystemExit(main())
