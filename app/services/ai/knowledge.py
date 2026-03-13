"""
Knowledge Context Service.

Centralized module for:
- RAG context retrieval
- PTES methodology guidance
- Tool capability context
- Avoiding duplicate code across agents
"""

import logging
from datetime import UTC
from typing import Any

from app.services.ai.rag import RAGService

logger = logging.getLogger(__name__)


# --- Singleton RAG Connection ---


_rag_service: RAGService | None = None


async def get_rag_service() -> RAGService:
    """Get singleton RAG service instance."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
        await _rag_service.initialize()
    return _rag_service


async def close_rag_service() -> None:
    """Close the RAG service connection."""
    global _rag_service
    if _rag_service is not None:
        _rag_service = None


# --- PTES Methodology Guidance ---


PTES_METHODOLOGY = {
    "scope": """
**PTES Phase 1 - Pre-engagement & Scoping:**
- Define target boundaries (IP ranges, domains, URLs)
- Clarify rules of engagement and exclusions
- Identify time windows and authorization
- Document approval requirements
""",
    "discovery": """
**PTES Phase 2 - Intelligence Gathering:**
- Passive reconnaissance (OSINT, DNS, WHOIS)
- Active port scanning and service detection
- Network mapping and topology discovery
- Technology fingerprinting
""",
    "enumeration": """
**PTES Phase 3 - Threat Modeling & Enumeration:**
- Service version enumeration (banners, fingerprints)
- Web application discovery (directories, files, endpoints)
- User and credential enumeration
- CMS and framework detection
""",
    "vulnerability": """
**PTES Phase 4 - Vulnerability Analysis:**
- Automated vulnerability scanning
- CVE matching and correlation
- Manual verification of findings
- Risk prioritization (CVSS, exploitability)
""",
    "exploitation": """
**PTES Phase 5 - Exploitation:**
- Select exploits based on discovered vulnerabilities
- Configure payloads for target environment
- Attempt exploitation with increasing aggression
- Document all attempts and outcomes
- Verify access level achieved
""",
    "post_exploitation": """
**PTES Phase 6 - Post-Exploitation:**
- Maintain access (persistence)
- Privilege escalation
- Lateral movement
- Data exfiltration (proof of concept)
- Clean up and restore
""",
    "reporting": """
**PTES Phase 7 - Reporting:**
- Executive summary
- Technical findings with evidence
- Risk ratings and business impact
- Remediation recommendations
- Attack narrative and timeline
""",
}


def get_methodology_guidance(phase: str) -> str:
    """Get PTES methodology guidance for a specific phase."""
    return PTES_METHODOLOGY.get(phase, "Follow standard penetration testing methodology.")


def get_full_methodology() -> str:
    """Get complete PTES methodology summary for planning."""
    return "\n".join(
        [
            "**PTES Methodology (Penetration Testing Execution Standard):**",
            "",
            *[
                f"{i + 1}. **{phase.title()}**{guidance}"
                for i, (phase, guidance) in enumerate(PTES_METHODOLOGY.items())
            ],
        ]
    )


# --- RAG Context Retrieval ---


async def get_exploit_context(
    query: str,
    _target: str | None = None,
    max_tokens: int = 1000,
) -> str:
    """Get relevant past exploits and CVEs from knowledge base."""
    try:
        rag = await get_rag_service()

        context = await rag.get_context_for_prompt(
            query=query,
            max_tokens=max_tokens,
            doc_types=["exploit_success", "exploit_failure", "cve"],
        )

        if context:
            return f"\n--- Past Exploits & CVEs ---\n{context}\n"
        return ""

    except Exception as e:
        logger.warning("Failed to get exploit context: %s", e)
        return ""


async def get_tool_usage_context(
    phase: str,
    services: list[dict[str, Any]] | None = None,
    max_tokens: int = 800,
) -> str:
    """Get relevant past tool usage from knowledge base."""
    try:
        rag = await get_rag_service()

        # Build query from phase and services
        query_parts = [phase]
        if services:
            for svc in services[:3]:
                if svc.get("service"):
                    query_parts.append(svc["service"])

        query = " ".join(query_parts)

        context = await rag.get_context_for_prompt(
            query=query, max_tokens=max_tokens, doc_types=["exploit_success", "finding"]
        )

        if context:
            return f"\n--- Past Successful Actions ---\n{context}\n"
        return ""

    except Exception as e:
        logger.warning("Failed to get tool usage context: %s", e)
        return ""


async def get_mission_context(
    directive: str,
    target: str | None = None,
    max_tokens: int = 800,
) -> str:
    """Get relevant past missions from knowledge base."""
    try:
        rag = await get_rag_service()

        query = f"{directive} {target or ''}"

        context = await rag.get_context_for_prompt(
            query=query, max_tokens=max_tokens, doc_types=["exploit_success", "finding"]
        )

        if context:
            return f"\n--- Past Successful Approaches ---\n{context}\n"
        return ""

    except Exception as e:
        logger.warning("Failed to get mission context: %s", e)
        return ""


# --- Tool Context ---


async def get_available_tools_context(grouped: bool = True) -> str:
    """Get list of all registered tools and their capabilities.

    Tools will be auto-installed when first used, so we show all registered tools.
    Status is synced from cache (set by tools container worker).
    """
    try:
        from app.services.tools.registry import get_registry

        registry = get_registry()

        # Sync tool status from cache before displaying
        try:
            await registry.sync_status_from_cache()
        except Exception as e:
            logger.debug("Failed to sync tool status: %s", e)

        # Show ALL tools, not just available ones - they will be auto-installed when used
        tools = registry.list_tools()

        if not tools:
            return ""

        if grouped:
            # Group tools by category
            by_category: dict[str, list[str]] = {}
            for tool in tools:
                cat = tool.config.category
                if cat not in by_category:
                    by_category[cat] = []
                status_marker = "[ready]" if tool.is_available else "[pending]"
                by_category[cat].append(f"{tool.config.name} ({tool.config.id}) {status_marker}")

            lines = ["**Available Security Tools** ([ready]=installed, [pending]=will auto-install):"]

            for cat, tool_names in by_category.items():
                lines.append(f"- {cat}: {', '.join(tool_names)}")

            return "\n".join(lines) + "\n"
        else:
            # Detailed list with descriptions
            tool_descriptions = []
            for tool in tools[:15]:  # Limit to avoid prompt overflow
                caps = ", ".join([c.value for c in tool.config.metadata.capabilities[:3]])
                status = "installed" if tool.is_available else "auto-install"
                tool_descriptions.append(
                    f"- {tool.config.name} [{status}]: {tool.config.description[:100]}... (Capabilities: {caps})"
                )

            return "--- Security Tools ---\n" + "\n".join(tool_descriptions) + "\n"

    except Exception as e:
        logger.warning("Failed to get tools context: %s", e)
        return ""


# --- Knowledge Base Indexing ---


async def index_exploit_attempt(
    vector_name: str,
    vector_type: str,
    target_ref: str,
    tool_used: str,
    payload: str | None,
    success: bool,
    output: str,
    error: str | None,
    blocked_by: str | None,
    priority: str,
    mission_id: str,
    target: str,
) -> bool:
    """Save exploit attempt to knowledge base for learning."""
    try:
        import json
        from datetime import datetime

        from app.services.ai.rag import Document

        rag = await get_rag_service()

        doc_type = "exploit_success" if success else "exploit_failure"

        content = json.dumps(
            {
                "vector_name": vector_name,
                "vector_type": vector_type,
                "target_ref": target_ref,
                "tool_used": tool_used,
                "payload": payload,
                "success": success,
                "output_summary": output[:500],
                "error": error,
                "blocked_by": blocked_by,
                "priority": priority,
            }
        )

        doc = Document(
            id=f"{doc_type}-{vector_name.replace(' ', '-')}-{int(datetime.now(UTC).timestamp())}",
            content=content,
            doc_type=doc_type,
            metadata={
                "success": success,
                "tool": tool_used,
                "mission_id": mission_id,
            },
            cve_id=None,
            severity=None,
            target=target,
            session_id=mission_id,
        )

        await rag.index_document(doc)
        logger.info("Indexed %s to knowledge base: %s", doc_type, vector_name)
        return True

    except Exception as e:
        logger.warning("Failed to index exploit attempt: %s", e)
        return False
