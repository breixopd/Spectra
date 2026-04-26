# AI Missions Training Audit

## Critical / High

- `.env.test` contains live provider credentials. It must remain uncommitted; rotate if it was ever committed or shared.
- TensorZero metrics are partially wired: `task_success` feedback is sent, but `send_exploit_feedback` and `send_quality_score` are not called by mission/report paths.
- Live mission tests create missions and validate API shape, but do not consistently poll to terminal mission state or verify target findings.
- Free OpenRouter models are volatile. Live tests must handle model `404` and `429` as provider availability, not platform auth failure.
- TensorZero currently sends developer-role messages, so configured OpenRouter models must support developer instructions. Gemma 3 free rejected that role during live mission testing.

## Live Target Notes

- Compose test stack includes Metasploitable and DVWA-style target wiring.
- Separate `docker/targets/` compose flow has additional target levels and needs clearer single workflow.
- Safety policy may block some intentionally aggressive lab commands; mission tests need explicit scope/policy settings.
- Direct mission smoke against `metasploitable` created a mission and advanced through scope setup. Follow-up run still timed out under live provider latency/health pressure; logs show TensorZero health requests taking 5-27s and scheduler DB pool exhaustion in the test stack. Scheduler test pool override was added, but mission E2E still needs a deterministic nightly harness with longer timeouts and provider health gating.

## Training Path

- Existing models/API/dataset services support opt-in dataset export and admin training concepts.
- Recommended next path: JSONL export of opted-in mission turns, PII scrub, eval holdout, Unsloth Colab/rented GPU script, progress callback token, artifact upload to object storage, then admin approval before model routing.
- Gemma/Qwen remain good candidates, but start with LoRA adapters and offline eval before production routing.
