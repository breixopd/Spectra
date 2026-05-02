# Semantic / code-search index freshness

**Date:** 2026-05-01

MCP-style `code_research` answers are only as current as the ingested snapshot. After router refactors (`spectra_api/routing.py` replacing older monolithic router tables, fail-closed `SERVICE_MODE`, removal of obsolete split-mode API stubs), **automated narrative may still cite old paths and behaviours**.

**Mitigation:** refresh the index from the same commit as your working tree (re-run ingestion on the host or job that builds the index). Until then, verify any architecture claims from search tools against `git grep` and direct file reads.
