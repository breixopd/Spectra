"""Post-mission checkpointing: lesson recording and RAG indexing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.mission.mission import Mission

logger = logging.getLogger("spectra.mission.manager.checkpoint")


def record_mission_lessons(mission: Mission) -> None:
    """Extract lessons from the completed mission and persist them."""
    try:
        from app.services.ai.memory import get_memory

        memory = get_memory()

        # Detect duplicate/low-value finding templates as false positives
        template_counts: dict[str, int] = {}
        for finding in mission.findings:
            template = finding.get("template-id") or finding.get("name", "")
            if template:
                template_counts[template] = template_counts.get(template, 0) + 1

        for template, count in template_counts.items():
            severity = next(
                (
                    f.get("severity", "info")
                    for f in mission.findings
                    if (f.get("template-id") or f.get("name")) == template
                ),
                "info",
            )
            if count >= 5 and severity == "info":
                memory.record_false_positive(template)
                mission.log(
                    f"[LEARN] Marked '{template}' as probable false positive ({count} duplicates)"
                )

        # Record OS profile if detected
        os_family = getattr(mission, "_detected_os", None)
        if os_family and os_family != "unknown":
            services = [
                s.service for s in mission.attack_surface.services if s.service
            ]
            memory.update_target_profile(
                os_family,
                services=services,
                note=(
                    f"Mission against {mission.target}: {len(mission.findings)} findings, "
                    f"{len(mission.tools_run)} tools used"
                ),
            )

        stats = memory.get_stats()
        mission.log(
            f"[LEARN] Memory updated: {stats['tool_lessons']} tool lessons, "
            f"{stats['exploit_lessons']} exploit patterns, {stats['target_profiles']} OS profiles"
        )

    except Exception as e:
        logger.debug("Post-mission learning failed (non-critical): %s", e)


async def index_to_rag(mission: Mission) -> None:
    """Index mission findings and outcomes into RAG for future retrieval."""
    try:
        from app.models.attack_surface import VectorStatus
        from app.services.ai.knowledge import get_rag_service
        from app.services.ai.rag import Document
        from app.services.rag.service import get_rag_facade

        rag = await get_rag_service()
        if not rag.is_functional:
            return

        facade = get_rag_facade()
        mission_id = str(mission.id)
        indexed = 0

        # Index findings via facade (max 20)
        for finding in mission.findings[:20]:
            finding_with_host = {**finding, "host": finding.get("host", mission.target)}
            if await facade.index_finding(finding_with_host, mission_id=mission_id):
                indexed += 1

        # Index tool outputs via facade (max 10 tools)
        for tool_name in (mission.tools_run or [])[:10]:
            await facade.index_tool_output(
                mission_id=mission_id,
                tool_name=tool_name,
                output=f"Tool {tool_name} executed against {mission.target}",
                target=mission.target,
            )
            indexed += 1

        # Index successful exploit vectors (max 10)
        if mission.attack_surface:
            successful = [
                v
                for v in mission.attack_surface.vectors
                if v.status == VectorStatus.SUCCESS
            ][:10]
            for vector in successful:
                tool = (
                    vector.suggested_tools[0] if vector.suggested_tools else "manual"
                )
                doc = Document(
                    id=f"exploit-{mission_id}-{vector.id}",
                    content=(
                        f"Successfully exploited {vector.target_ref} on "
                        f"{mission.target} using {tool}. "
                        f"Attack: {vector.name}. "
                        f"Type: {vector.target_type}."
                    ),
                    doc_type="exploit_success",
                    target=mission.target,
                    session_id=mission_id,
                    metadata={
                        "target_type": vector.target_type,
                        "tool": tool,
                    },
                )
                await rag.index_document(doc)
                indexed += 1

        # Index mission summary
        tools_str = (
            ", ".join(mission.tools_run[:8]) if mission.tools_run else "none"
        )
        doc = Document(
            id=f"mission-{mission_id}",
            content=(
                f"Pentest of {mission.target}: {len(mission.findings)} findings, "
                f"{len(mission.tools_run)} tools used ({tools_str}). "
                f"Status: {mission.status}. "
                f"Directive: {mission.directive[:200]}"
            ),
            doc_type="mission_summary",
            target=mission.target,
            session_id=mission_id,
        )
        await rag.index_document(doc)
        indexed += 1

        # Index debrief lessons from logs (max 10)
        lessons = [
            entry
            for entry in (mission.logs or [])
            if isinstance(entry, str) and "[LEARN]" in entry
        ][:10]
        for i, lesson in enumerate(lessons):
            doc = Document(
                id=f"lesson-{mission_id}-{i}",
                content=lesson,
                doc_type="lesson",
                target=mission.target,
                session_id=mission_id,
                metadata={"source": "debrief", "mission_id": mission_id},
            )
            await rag.index_document(doc)
            indexed += 1

        mission.log(f"[RAG] Indexed {indexed} documents for future reference")
    except Exception as e:
        logger.debug("RAG indexing failed (non-critical): %s", e)
