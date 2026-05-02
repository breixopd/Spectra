"""Mission launch compliance and abuse-prevention checks."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

HIGH_RISK_TERMS = {
    "credential stuffing",
    "ddos",
    "denial of service",
    "exfiltrate",
    "exfiltration",
    "malware",
    "phishing",
    "persistence",
    "ransomware",
    "reverse shell",
}


@dataclass(frozen=True)
class MissionAbuseDecision:
    """Result of a mission abuse-prevention check."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    risk_score: int = 0
    requires_review: bool = False


def _extract_host(target: str) -> str:
    candidate = target.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    return (parsed.hostname or candidate).strip("[]")


def _target_network(target: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    host = target.strip() if "/" in target and "://" not in target else _extract_host(target)
    try:
        return ipaddress.ip_network(host, strict=False)
    except ValueError:
        return None


def _is_broad_public_network(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    if not network.is_global:
        return False
    if isinstance(network, ipaddress.IPv4Network):
        return network.prefixlen < 24
    return network.prefixlen < 64


def evaluate_mission_abuse(
    *,
    target: str,
    directive: str,
    requirements: str | None,
    authorization_confirmed: bool,
    requires_approval: bool,
) -> MissionAbuseDecision:
    """Reject obviously unsafe mission launches before they reach agents/tools."""

    reasons: list[str] = []
    risk_score = 0

    if not authorization_confirmed:
        reasons.append("target authorization was not confirmed")
        risk_score += 50

    network = _target_network(target)
    if network and _is_broad_public_network(network):
        reasons.append("broad public network ranges require target verification and admin review")
        risk_score += 40

    text = f"{directive}\n{requirements or ''}".lower()
    matched_terms = sorted(term for term in HIGH_RISK_TERMS if re.search(rf"\b{re.escape(term)}\b", text))
    if matched_terms:
        reasons.append(f"high-risk techniques requested: {', '.join(matched_terms)}")
        risk_score += 30

    requires_review = risk_score >= 30
    allowed = not reasons or (requires_approval and not any("broad public network" in reason for reason in reasons))
    return MissionAbuseDecision(
        allowed=allowed,
        reasons=reasons,
        risk_score=risk_score,
        requires_review=requires_review,
    )
