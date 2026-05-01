# Platform quality iteration log

Structured **audit → research → implement** cycles toward launch readiness. Each numbered block is one loop (three steps condensed into bullets).

## Loops 1–5 (mission FSM + API polish)

1. **Audit:** `MissionState = MissionStatus` alias and `app.core` lazy export duplicated the enum. **Research:** Call sites limited to tests + `state_machine` internals. **Implement:** Removed alias; `PHASE_TO_STATE` / `phase_to_state` / FSM property use `MissionStatus` only; dropped `MissionState` from `app.core._SUBMODULE_MAP` and `state_machine.__all__`.
2. **Audit:** `tests/unit/core/test_core_infrastructure.py` mixed enum name with machine name after bulk replace. **Research:** Restore `MissionStateMachine` / `MissionStateError`. **Implement:** Fixed imports and identifiers; tests use `MissionStatus` for enum values.
3. **Audit:** `test_agent_improvements.py` still imported removed `MissionState`. **Research:** Redundant value-equality tests. **Implement:** Single `MissionStatus` import; stable string assertions; FSM assertions use `MissionStatus.*`.
4. **Audit:** Liveness JSON still advertised `"service": "app"` while the process is the API service image. **Research:** No unit test pinned the old string. **Implement:** Set `"spectra-api"` in `health.py` liveness payload.
5. **Audit:** Legacy backlog listed completed MissionState work. **Research:** Keep file accurate for operators. **Implement:** Removed completed P0 line from `legacy-cleanup-backlog.md`.

## Loops 6–10 (verification + docs alignment)

6. **Audit:** Post-change FSM must not regress. **Research:** Targeted pytest scope. **Implement:** (Run) `tests/unit/core/test_core_infrastructure.py`, `test_agent_improvements.py`, `test_state_machine.py` via Docker.
7. **Audit:** Static analysis on touched paths. **Research:** Ruff on repo slices. **Implement:** (Run) `ruff check` on changed files / full app+tests if clean.
8. **Audit:** Import boundaries after `app.core` map change. **Research:** `check_import_boundaries.py` rules. **Implement:** (Run) script inside `spectra-test-ci` image.
9. **Audit:** Operators need a traceable log of quality work, not only code. **Research:** Runbooks already own CI parity. **Implement:** This committed log under `docs/runbooks/`.
10. **Audit:** Open P0 still includes worker startup env and exploit type aliases. **Research:** Larger blast radius than one loop. **Implement:** Deferred — tracked only in `legacy-cleanup-backlog.md` for the next change set.

## Loops 11–15 (hardening mindset)

11. **Audit:** Billing refund automation still absent from prior roadmap. **Research:** Product contract vs Stripe webhooks. **Implement:** Deferred — needs product decision + `tests/unit/api/test_billing.py` extension.
12. **Audit:** VPN / mission-scope integration coverage gaps. **Research:** Existing `vpn_jobs` tests and mission routers. **Implement:** Deferred — schedule dedicated test PR.
13. **Audit:** Compose smoke job is heavy for every dev run. **Research:** `compose-smoke-ci.md` documents optional full stack. **Implement:** No change — CI parity script remains default gate.
14. **Audit:** Pyright adds latency to local gates. **Research:** `SKIP_PYRIGHT=1` documented in runbooks. **Implement:** No code change; use flag for inner loop.
15. **Audit:** Chunkhound / VPS index freshness. **Research:** Host-specific. **Implement:** Deferred — run reindex on deploy host after `git pull`.

## Loops 16–20 (release posture)

16. **Audit:** Pre-release checklist must reference real commands. **Research:** `pre-release-gate.md` already lists bandit / pip-audit / compose. **Implement:** Confirmed alignment with `.github/workflows/ci.yml` (no edit required this pass).
17. **Audit:** `MissionStateError` name vs `MissionStatus` rename confusion. **Research:** Exception is domain “invalid transition”, not the enum. **Implement:** No rename — keep `MissionStateError` in `spectra_common`.
18. **Audit:** Scheduler healthz tests. **Research:** Separate router module. **Implement:** No change this pass.
19. **Audit:** Customer-visible API payloads should stay backward compatible where documented. **Research:** Liveness `service` field is diagnostic, low risk. **Implement:** Document in changelog / release notes when shipping.
20. **Audit:** Stopping condition for this batch — green targeted tests + lint + import boundaries. **Research:** Full `ci-parity.sh ci` already green on branch in prior session. **Implement:** Re-run targeted Docker pytest after this diff; follow with full parity before merge.

---

**Next batch (suggested):** remove `WORKER_SKIP_STARTUP_AUTO_INSTALL` end-to-end; migrate exploit aliases; add billing refund webhook tests; add VPN policy unit tests; run `./scripts/runbooks/ci-parity.sh all` before release tag.
