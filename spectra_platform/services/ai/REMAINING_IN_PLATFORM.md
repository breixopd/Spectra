# What stays under `spectra_platform.services.ai`

Mission agents (`agents/`), **consensus**, **context**, **memory**, **knowledge** (facade),
**playbook**, **CVE intel**, **blackboard**, **event_bus**, etc. remain here
because they depend on `spectra_platform` models, repositories, mission runtime, or tool dispatch.

The **AI runtime** (TensorZero router, embedding + RAG engine, LLM client base, shared prompts,
sanitization, structured agent errors, cost tracker) lives in `spectra_ai` and is wired into the
API via `spectra_platform.core.database` (async session maker for RAG) and `spectra_platform.telemetry.telemetry`
(LLM metrics hook).
