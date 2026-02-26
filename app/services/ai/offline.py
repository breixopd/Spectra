"""
Offline mode — run pentests without an LLM using playbook-only execution.

When the LLM provider is unreachable, Spectra can still function by:
1. Using the PlaybookEngine for deterministic tool selection
2. Using CVE intelligence for exploit matching
3. Using default credential lists for auth testing
4. Generating reports from structured data

This provides degraded but functional operation in air-gapped environments.
"""

import logging
from typing import Any

from app.services.ai.cve_intel import lookup_cves
from app.services.ai.playbook import get_playbook_engine
from app.services.ai.wordlists import generate_credential_list  # noqa: F401  — re-exported for offline consumers

logger = logging.getLogger("spectra.ai.offline")


async def run_playbook_mission(target: str, services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run a mission using only playbooks (no LLM needed)."""
    engine = get_playbook_engine()
    tasks = []

    for svc in services:
        service = svc.get("service", "")
        port = svc.get("port")
        product = svc.get("product", "")

        playbook = engine.get_playbook_for_service(service, port)
        if playbook:
            for step in playbook.steps:
                tasks.append({
                    "tool": step.tool,
                    "target": target,
                    "args": step.args,
                    "description": step.description,
                    "phase": "offline_playbook",
                })

        # Add CVE-specific tasks
        cves = lookup_cves(product=product, version=svc.get("version"))
        for cve in cves[:2]:
            if cve.get("version_match"):
                tasks.append({
                    "tool": "searchsploit",
                    "target": target,
                    "args": {"query": cve["cve"]},
                    "description": f"Search exploit for {cve['cve']}: {cve['description']}",
                    "phase": "offline_cve",
                })

    return tasks


def check_offline_capability() -> dict[str, Any]:
    """Check what's available for offline operation."""
    engine = get_playbook_engine()
    return {
        "playbooks_available": len(engine.playbooks),
        "cve_database_entries": len(lookup_cves(product="apache") + lookup_cves(product="openssh")),
        "offline_ready": len(engine.playbooks) > 0,
        "limitations": [
            "No LLM-based tool selection (uses playbooks)",
            "No custom exploit generation",
            "No AI-powered report generation",
            "Limited to built-in CVE database",
        ],
    }
