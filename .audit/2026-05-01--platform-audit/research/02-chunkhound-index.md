# Chunkhound index freshness

**Date:** 2026-05-01

`code_research` answers are only as current as the ingested snapshot. After router refactors (`spectra_api/routing.py` replacing monolithic `spectra_platform/main.py` router tables, fail-closed `SERVICE_MODE`, removal of fake `ai`/`worker`/`scheduler` API-router modes), **semantic search may still cite old paths and behaviours**.

**Mitigation:** re-index from the same commit as your working tree (e.g. update the VPS / ingestion job that pushes to Chunkhound). Until then, verify any Chunkhound “architecture” claims against `git grep` / direct file reads.
