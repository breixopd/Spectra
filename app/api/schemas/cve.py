"""CVE Intelligence response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class CVEItem(BaseModel):
    """Single CVE entry returned by lookup."""

    cve_id: str | None = None
    description: str | None = None
    severity: str | None = None
    cvss_score: float | None = None
    published: str | None = None
    references: list[str] = []


class CVELookupResponse(BaseModel):
    """Response for CVE lookup."""

    cves: list[CVEItem]
    total: int | None = None
    query: dict
    message: str | None = None


class MetasploitModule(BaseModel):
    """Single Metasploit module entry."""

    name: str | None = None
    fullname: str | None = None
    description: str | None = None
    rank: str | None = None


class CVEExploitsResponse(BaseModel):
    """Response for CVE exploit modules."""

    cve_id: str
    exploit_available: bool
    metasploit_modules: list[dict]
    total: int


class CVEEnrichedResponse(BaseModel):
    """Response for enriched CVE data."""

    cve_id: str | None = None
    exploitdb: list[dict] = []
    metasploit: list[dict] = []
    epss: float | dict | None = None
    kev: bool | dict | None = None


class SearchExploitResponse(BaseModel):
    """Response for ExploitDB search."""

    query: str
    exploitdb_results: list[dict]
    metasploit_modules: list[dict]
    total: int
