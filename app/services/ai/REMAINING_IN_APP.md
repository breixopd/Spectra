# What stays under `app.services.ai`

Mission agents (`agents/`), **consensus**, **context**, **memory**, **knowledge** (facade),
**playbook**, **CVE intel**, **adaptive** flows, **blackboard**, **event_bus**, etc. remain here
because they depend on `app` models, repositories, mission runtime, or tool dispatch.

The **AI runtime** (TensorZero router, embedding + RAG engine, LLM client base, shared prompts,
sanitization, structured agent errors, cost tracker) lives in `spectra_ai` and is wired into the
API via `app.core.database` (async session maker for RAG) and `app.telemetry.telemetry`
(LLM metrics hook).
