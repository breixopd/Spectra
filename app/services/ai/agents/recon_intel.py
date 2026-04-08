"""ReconIntelAgent — OSINT / web intelligence gathering for recon enrichment.

Privacy-safe: NEVER discloses target identifiers (IPs, domains) to external APIs.
All external queries are sanitized through ``OsintSanitizer`` before transmission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.core.constants import (
    CISA_KEV_URL,
    CVE_CACHE_TTL,
    EPSS_API_URL,
    EXTERNAL_HTTP_TIMEOUT,
    NVD_API_BASE_URL,
    NVD_RATE_LIMIT_DELAY,
    NVD_RATE_LIMIT_DELAY_WITH_KEY,
)
from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)
from app.services.ai.agents.registry import register_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Privacy sanitizer
# ---------------------------------------------------------------------------


class OsintSanitizer:
    """Ensures no target-identifying information leaks to external APIs."""

    _IP_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    _DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")
    _INTERNAL_PATTERN = re.compile(r"\b(?:10\.\d+|192\.168\.\d+|172\.(?:1[6-9]|2\d|3[01])\.)\.\d+\b")

    # Well-known domains that are *not* target identifiers
    _SAFE_DOMAINS = frozenset(
        {
            "nvd.nist.gov",
            "nist.gov",
            "cisa.gov",
            "api.first.org",
            "first.org",
            "services.nvd.nist.gov",
            "www.cisa.gov",
            "exploit-db.com",
            "github.com",
            "cve.org",
        }
    )

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Remove all target-identifying information from text."""
        text = cls._INTERNAL_PATTERN.sub("[REDACTED_IP]", text)
        text = cls._IP_PATTERN.sub("[REDACTED_IP]", text)

        # Only strip domains that aren't in the safe-list
        def _replace_domain(m: re.Match[str]) -> str:
            domain = m.group(0).lower()
            if domain in cls._SAFE_DOMAINS:
                return m.group(0)
            return "[REDACTED_DOMAIN]"

        text = cls._DOMAIN_PATTERN.sub(_replace_domain, text)
        return text

    @classmethod
    def validate_safe_for_external(cls, data: dict[str, Any]) -> bool:
        """Return True only if *data* contains no target identifiers."""
        serialized = json.dumps(data, default=str)
        if cls._INTERNAL_PATTERN.search(serialized):
            return False
        if cls._IP_PATTERN.search(serialized):
            return False
        # Check for non-safe domains
        return all(match.group(0).lower() in cls._SAFE_DOMAINS for match in cls._DOMAIN_PATTERN.finditer(serialized))


# ---------------------------------------------------------------------------
# Input / Output models
# ---------------------------------------------------------------------------

QueryType = Literal["cve_lookup", "technology_intel", "service_fingerprint", "exploit_search"]


class ReconIntelInput(BaseModel):
    """Input for OSINT gathering."""

    query_type: QueryType
    technology: str | None = None
    service: str | None = None
    version: str | None = None
    cve_ids: list[str] = Field(default_factory=list)
    # NEVER include IP addresses or domains in inputs sent to external APIs


class ReconIntelOutput(AgentAction):
    """Results from OSINT gathering."""

    action_type: str = "intel_gathered"
    intel_type: str  # matches query_type
    findings: list[dict[str, Any]] = Field(default_factory=list)
    cve_details: list[dict[str, Any]] = Field(default_factory=list)
    exploit_references: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@register_agent
class ReconIntelAgent(Agent[ReconIntelInput, ReconIntelOutput]):
    """Gathers public intelligence from web sources to enrich recon data."""

    role = AgentRole.RECON_INTEL
    name = "ReconIntelAgent"
    description = "Gathers public intelligence from web sources to enrich recon data"

    # ------------------------------------------------------------------
    # NVD
    # ------------------------------------------------------------------

    async def _query_nvd(self, cve_ids: list[str]) -> list[dict[str, Any]]:
        """Query NVD API v2 for CVE details."""
        if not cve_ids:
            return []

        from app.core.config import settings

        api_key: str | None = getattr(settings, "NVD_API_KEY", None)
        delay = NVD_RATE_LIMIT_DELAY_WITH_KEY if api_key else NVD_RATE_LIMIT_DELAY
        headers: dict[str, str] = {}
        if api_key:
            headers["apiKey"] = api_key

        results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=EXTERNAL_HTTP_TIMEOUT) as client:
            for i, cve_id in enumerate(cve_ids):
                if i > 0:
                    await asyncio.sleep(delay)

                params: dict[str, str] = {"cveId": cve_id}
                if not OsintSanitizer.validate_safe_for_external(params):
                    logger.warning("Sanitizer blocked NVD query for %s", cve_id)
                    continue

                try:
                    resp = await client.get(NVD_API_BASE_URL, params=params, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as exc:
                    logger.warning("NVD query failed for %s: %s", cve_id, exc)
                    continue

                for vuln in data.get("vulnerabilities", []):
                    cve_data = vuln.get("cve", {})
                    metrics = cve_data.get("metrics", {})
                    cvss_v31 = (
                        (metrics.get("cvssMetricV31", [{}])[0].get("cvssData", {}))
                        if metrics.get("cvssMetricV31")
                        else {}
                    )

                    descriptions = cve_data.get("descriptions", [])
                    desc = next(
                        (d["value"] for d in descriptions if d.get("lang") == "en"),
                        "",
                    )

                    results.append(
                        {
                            "cve_id": cve_data.get("id", cve_id),
                            "description": desc,
                            "cvss_score": cvss_v31.get("baseScore"),
                            "cvss_vector": cvss_v31.get("vectorString"),
                            "severity": cvss_v31.get("baseSeverity"),
                            "references": [r.get("url") for r in cve_data.get("references", []) if r.get("url")],
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # CISA KEV
    # ------------------------------------------------------------------

    async def _query_cisa_kev(self) -> dict[str, Any]:
        """Load CISA KEV catalog, caching in PostgreSQL for 24h."""
        from app.services.exploit_db import get_exploit_db

        db = get_exploit_db()

        # Check PostgreSQL cache
        cached = await db._cache_get("recon_kev_catalog")
        if cached is not None:
            return cached

        async with httpx.AsyncClient(timeout=EXTERNAL_HTTP_TIMEOUT) as client:
            try:
                resp = await client.get(CISA_KEV_URL)
                resp.raise_for_status()
                data = resp.json()
                await db._cache_set("recon_kev_catalog", data, CVE_CACHE_TTL)
                return data
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch CISA KEV: %s", exc)
                return {}

    async def _check_kev(self, cve_ids: list[str]) -> list[dict[str, Any]]:
        """Check which CVEs appear in CISA KEV catalog."""
        if not cve_ids:
            return []

        kev_data = await self._query_cisa_kev()
        vulns = kev_data.get("vulnerabilities", [])
        kev_set = {v.get("cveID") for v in vulns}

        return [
            {
                "cve_id": cve_id,
                "in_kev": cve_id in kev_set,
                "kev_detail": next((v for v in vulns if v.get("cveID") == cve_id), None),
            }
            for cve_id in cve_ids
            if cve_id in kev_set
        ]

    # ------------------------------------------------------------------
    # EPSS
    # ------------------------------------------------------------------

    async def _query_epss(self, cve_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch EPSS exploit-probability scores."""
        if not cve_ids:
            return []

        params: dict[str, str] = {"cve": ",".join(cve_ids)}
        if not OsintSanitizer.validate_safe_for_external(params):
            logger.warning("Sanitizer blocked EPSS query")
            return []

        async with httpx.AsyncClient(timeout=EXTERNAL_HTTP_TIMEOUT) as client:
            try:
                resp = await client.get(EPSS_API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as exc:
                logger.warning("EPSS query failed: %s", exc)
                return []

        results: list[dict[str, Any]] = []
        for entry in data.get("data", []):
            results.append(
                {
                    "cve_id": entry.get("cve"),
                    "epss_score": float(entry.get("epss", 0)),
                    "percentile": float(entry.get("percentile", 0)),
                }
            )
        return results

    # ------------------------------------------------------------------
    # ExploitDB (local index via existing service)
    # ------------------------------------------------------------------

    async def _query_exploitdb(self, technology: str | None, version: str | None) -> list[dict[str, Any]]:
        """Search local ExploitDB index."""
        from app.services.exploit_db import ExploitDatabase

        query_parts = [p for p in (technology, version) if p]
        if not query_parts:
            return []

        query = " ".join(query_parts)
        db = ExploitDatabase()
        # ExploitDatabase.search_exploitdb is synchronous
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, db.search_exploitdb, query)

    # ------------------------------------------------------------------
    # RAG historical context
    # ------------------------------------------------------------------

    async def _query_rag_history(self, query: str) -> list[dict[str, Any]]:
        """Retrieve historical findings/exploits from RAG for context."""
        try:
            from app.services.rag.service import get_rag_facade

            facade = get_rag_facade()
            results = await facade.search(query, limit=5)
            return [
                {
                    "source": "rag_history",
                    "doc_type": r.document.doc_type,
                    "content": r.document.content[:500],
                    "score": r.score,
                    "severity": r.document.severity,
                }
                for r in results
            ]
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("RAG history query failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # LLM enrichment
    # ------------------------------------------------------------------

    async def _enrich_with_llm(
        self,
        context: AgentContext,
        technology: str | None,
        findings: list[dict[str, Any]],
    ) -> list[str]:
        """Ask the LLM to synthesize intelligence into recommendations."""
        if not findings:
            return []

        sanitized = OsintSanitizer.sanitize(json.dumps(findings, default=str))
        tech_label = technology or "the target service"

        prompt = (
            f"Given these OSINT findings about {tech_label}, "
            "what attack vectors are most promising? "
            "Return a concise bullet list of actionable recommendations.\n\n"
            f"Findings:\n{sanitized}"
        )

        try:
            response = await self._llm_generate(
                messages=[
                    {"role": "system", "content": self._build_system_prompt(context)},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            text = response if isinstance(response, str) else str(response)
            return [
                line.lstrip("-•* ").strip()
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except (OSError, RuntimeError, ValueError, TimeoutError):
            logger.exception("LLM enrichment failed")
            return []

    # ------------------------------------------------------------------
    # execute()
    # ------------------------------------------------------------------

    async def execute(
        self,
        context: AgentContext,
        input_data: ReconIntelInput,
    ) -> AgentResult:
        qt = input_data.query_type
        cve_ids = input_data.cve_ids
        technology = input_data.technology
        version = input_data.version

        all_findings: list[dict[str, Any]] = []
        cve_details: list[dict[str, Any]] = []
        exploit_refs: list[dict[str, Any]] = []
        recommendations: list[str] = []

        try:
            # Build concurrent tasks depending on query_type
            tasks: dict[str, Any] = {}

            if qt in ("cve_lookup", "technology_intel", "service_fingerprint") and cve_ids:
                tasks["nvd"] = self._query_nvd(cve_ids)
                tasks["kev"] = self._check_kev(cve_ids)
                tasks["epss"] = self._query_epss(cve_ids)

            if qt in ("technology_intel", "service_fingerprint", "exploit_search"):
                tasks["exploitdb"] = self._query_exploitdb(technology, version)

            # RAG: retrieve historical context for similar targets/technologies
            rag_query_parts = [p for p in (technology, version) if p]
            if rag_query_parts:
                tasks["rag_history"] = self._query_rag_history(" ".join(rag_query_parts))

            # Execute concurrently
            if tasks:
                keys = list(tasks.keys())
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                source_results = dict(zip(keys, results, strict=True))
            else:
                source_results = {}

            # Aggregate
            for key, result in source_results.items():
                if isinstance(result, BaseException):
                    logger.warning("Source %s failed: %s", key, result)
                    continue

                if key == "nvd":
                    cve_details.extend(result)
                    all_findings.extend(result)
                elif key == "kev" or key == "epss":
                    all_findings.extend(result)
                elif key == "exploitdb":
                    exploit_refs.extend(result)
                    all_findings.extend(result)
                elif key == "rag_history":
                    all_findings.extend(result)

            # LLM enrichment (optional, only if we have findings)
            if all_findings:
                recommendations = await self._enrich_with_llm(context, technology, all_findings)

            confidence = min(0.9, 0.3 + 0.1 * len(all_findings))

            output = ReconIntelOutput(
                intel_type=qt,
                confidence=confidence,
                risk_level=ActionRisk.LOW,
                reasoning=f"Gathered intelligence from {len(source_results)} sources",
                findings=all_findings,
                cve_details=cve_details,
                exploit_references=exploit_refs,
                recommendations=recommendations,
            )
            return AgentResult(success=True, action=output)

        except (OSError, RuntimeError, ValueError, TimeoutError):
            logger.exception("ReconIntelAgent execution failed")
            return AgentResult(
                success=False,
                error="Intelligence gathering failed — see logs for details",
            )
