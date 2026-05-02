# Subagent return notes

- **Architecture (explore):** Hybrid `services/*` importing `app`; duplicate health prefixes; `SERVICE_MODE` fallback widened surface; `MissionState` / exploit aliases; worker dual health paths.
- **Security (explore):** Compose dev defaults; `create_subprocess_shell` in executor + worker helpers; CORS+credentials; config auto-secrets in non-prod.
- **Tests/CI (explore):** CI omitted `spectra_api` from `--cov=` vs pyproject; integration skips `e2e`/`live`; no UI job on PR; ruff scope `spectra_platform/`+`tests/` only.

Parent merged into `plan/01-improvement-plan.md` and implemented P0 subset (SERVICE_MODE + CI cov alignment). **2026-05-01 follow-up:** verification doc, `spectra_ai` in coverage gate, expanded ruff paths, Swarm header note, `CommandBuilder` metachar tests, Chunkhound lag documented in `research/02-chunkhound-index.md`.
