"""POC Deep Research — enhanced vulnerability research for exploit generation.

When standard exploits fail, this module performs deep research:
1. Exact software version + patch notes → what changed
2. GitHub issues/commits for the target component → find unreleased fixes
3. Dependency chain analysis → vulnerable transitive dependencies
4. Similar CVEs on related products → adapt exploit patterns

All research is version-specific and evidence-driven.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    """Results of deep vulnerability research."""

    target: str
    software_name: str
    software_version: str
    cve_ids: list[str] = field(default_factory=list)
    patch_notes: str = ""
    github_leads: list[dict[str, str]] = field(default_factory=list)
    dependency_vulns: list[dict[str, str]] = field(default_factory=list)
    similar_cves: list[dict[str, str]] = field(default_factory=list)
    exploit_hints: list[str] = field(default_factory=list)
    confidence: float = 0.0


class DeepResearcher:
    """Performs deep research on a target component to find exploit opportunities.

    Designed to be called by the POC Developer agent when standard exploit
    databases don't yield results. Uses multiple research vectors to find
    unpublished vulnerabilities, dependency issues, and related CVEs.

    Usage:
        researcher = DeepResearcher()
        result = await researcher.research("Apache", "2.4.49", "10.0.0.1")
        # result.exploit_hints contains actionable leads
    """

    async def research(
        self,
        software_name: str,
        software_version: str,
        target: str = "",
    ) -> ResearchResult:
        """Perform deep research on a target software component.

        Args:
            software_name: Name of the software (e.g., "Apache httpd")
            software_version: Version string (e.g., "2.4.49")
            target: Target IP/hostname for context

        Returns:
            ResearchResult with CVE IDs, patch notes, exploit hints, etc.
        """
        result = ResearchResult(
            target=target,
            software_name=software_name,
            software_version=software_version,
        )

        # 1. Version-specific CVE lookup
        result.cve_ids = self._find_cves_for_version(software_name, software_version)

        # 2. Check for patch notes (what changed between versions)
        result.patch_notes = self._analyze_version_delta(software_name, software_version)

        # 3. GitHub leads (unpublished fixes, recent commits)
        result.github_leads = self._search_github_leads(software_name, software_version)

        # 4. Dependency chain analysis
        result.dependency_vulns = self._analyze_dependencies(software_name)

        # 5. Similar CVEs on related products
        result.similar_cves = self._find_similar_cves(software_name, software_version)

        # 6. Generate exploit hints
        result.exploit_hints = self._generate_exploit_hints(result)

        # 7. Calculate confidence
        result.confidence = self._calculate_confidence(result)

        logger.info(
            "Deep research on %s %s: %d CVEs, %d github leads, %.1f%% confidence",
            software_name, software_version,
            len(result.cve_ids), len(result.github_leads),
            result.confidence * 100,
        )

        return result

    # ── Research vectors ──────────────────────────────────────────────

    def _find_cves_for_version(self, name: str, version: str) -> list[str]:
        """Find CVEs specific to this software version."""
        cves: list[str] = []
        # This would query NVD/CISA APIs in production
        # For now, provide structured hints for the LLM to use in its search
        if name.lower() in ("apache", "apache httpd", "apache2"):
            if version.startswith(("2.4.49", "2.4.50")):
                cves.append("CVE-2021-42013")  # Path traversal
                cves.append("CVE-2021-41773")  # Path traversal
        elif name.lower() in ("nginx",):
            if version < "1.20.0":
                cves.append("CVE-2021-23017")  # DNS resolver
        elif name.lower() in ("openssh", "ssh") and version.startswith("8."):
            cves.append("CVE-2024-6387")  # regreSSHion

        return cves

    def _analyze_version_delta(self, name: str, version: str) -> str:
        """Suggest analyzing patch notes between this version and next."""
        parts = version.split(".")
        try:
            next_minor = ".".join(parts[:-1]) + "." + str(int(parts[-1]) + 1)
        except (ValueError, IndexError):
            next_minor = version
        return (
            f"Compare changelogs between {name} {version} and {name} {next_minor}. "
            f"Look for security fixes that indicate exploitable vulnerabilities in {version}. "
            f"Check the project's SECURITY.md, CHANGELOG, and release notes."
        )

    def _search_github_leads(self, name: str, version: str) -> list[dict[str, str]]:
        """Search for GitHub issues/commits related to security fixes."""
        leads: list[dict[str, str]] = []
        leads.append({
            "source": "github_commits",
            "query": f"{name} security fix after {version}",
            "hint": "Look for commits with 'security', 'fix CVE', 'patch vulnerability' in messages after this version was released",
        })
        leads.append({
            "source": "github_issues",
            "query": f"{name} vulnerability",
            "hint": "Check closed issues mentioning security vulnerabilities that were fixed silently",
        })
        return leads

    def _analyze_dependencies(self, name: str) -> list[dict[str, str]]:
        """Analyze dependency chains for known vulnerabilities."""
        deps: list[dict[str, str]] = []
        # Common dependency patterns
        dep_map = {
            "apache": ["openssl", "apr", "pcre", "libxml2"],
            "nginx": ["openssl", "pcre", "zlib"],
            "php": ["libxml2", "openssl", "curl", "sqlite"],
            "python": ["openssl", "libffi", "sqlite"],
            "node": ["openssl", "zlib", "libuv"],
        }
        for key, dep_list in dep_map.items():
            if key in name.lower():
                for dep in dep_list:
                    deps.append({
                        "dependency": dep,
                        "hint": f"Check if {dep} version used by {name} has known vulnerabilities",
                    })
        return deps

    def _find_similar_cves(self, name: str, version: str) -> list[dict[str, str]]:
        """Find CVEs on related/similar products that may have analogous exploits."""
        similar: list[dict[str, str]] = []

        product_families = {
            "apache": ["apache tomcat", "apache struts", "apache log4j"],
            "nginx": ["openresty", "haproxy", "traefik"],
            "tomcat": ["jetty", "jboss", "wildfly", "glassfish"],
            "iis": ["apache", "nginx"],
        }

        for key, family in product_families.items():
            if key in name.lower():
                for related in family:
                    similar.append({
                        "related_product": related,
                        "hint": f"CVEs in {related} often have analogous exploits in {name}. Check for similar attack patterns.",
                    })
                break

        return similar

    # ── Hint generation ───────────────────────────────────────────────

    def _generate_exploit_hints(self, result: ResearchResult) -> list[str]:
        """Generate actionable exploit hints from research results."""
        hints: list[str] = []

        if result.cve_ids:
            hints.append(f"Research exploit techniques for: {', '.join(result.cve_ids)}")

        if result.patch_notes:
            hints.append(result.patch_notes)

        if result.dependency_vulns:
            deps = [d["dependency"] for d in result.dependency_vulns[:3]]
            hints.append(f"Investigate vulnerable dependencies: {', '.join(deps)}")

        if result.similar_cves:
            similar = result.similar_cves[0]["related_product"]
            hints.append(f"Adapt exploit patterns from similar product: {similar}")

        if result.github_leads:
            hints.append(result.github_leads[0]["hint"])

        return hints

    def _calculate_confidence(self, result: ResearchResult) -> float:
        """Calculate research confidence based on available data."""
        score = 0.0

        if result.cve_ids:
            score += 0.3
        if result.patch_notes:
            score += 0.15
        if result.github_leads:
            score += 0.15
        if result.dependency_vulns:
            score += 0.2
        if result.similar_cves:
            score += 0.2

        return min(score, 1.0)
