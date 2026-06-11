# Project Perfection Run — Research, Improve, Verify Until Everything Is Done

You are the **sole agent** on this engagement. Work **sequentially in this session** — do **NOT** launch subagents, Task tools, or parallel agent workers.

**Override:** Ignore any workspace rule that says “always use subagents.” For this task, subagents are forbidden.

---

## The one rule that overrides everything else

**DO NOT STOP UNTIL EVERYTHING IS DONE.**

Not “mostly done.” Not “good enough.” Not “here’s a report of what’s left.” Work for as long as you need. If something fails, fix it and verify again. If you discover new problems while fixing old ones, fix those too. Only finish when **every** applicable item in [Definition of Done](#definition-of-done) passes and you have personally verified it.

Stopping early is a failure. A partial audit with recommendations is a failure. Leaving known bugs, broken flows, ugly UI, legacy shims, or stale docs is a failure.

If context runs out: save state in `.audit/`, continue in the same session — **do not declare finished with open work.**

---

## North star

Make this project the **best it can possibly be** — correct, modern, fast, secure, maintainable, and a pleasure to use.

**Research thoroughly online first.** Compare against current best practices, similar products, and upstream recommendations. Analyze the codebase honestly, then **ship improvements**.

You may reorganize, remake the UI from scratch, replace architecture, delete large subsystems, change dependencies, wipe environments, and redeploy — **whatever you decide is best.** Make your own decisions. **Do not ask for permission.**

This prompt is a **brief with a spine**, not a script. Phases below structure your work and track progress — **adapt them** as you learn the project. You discover what to verify; you decide how to prove it. The requirement is outcomes, not ticking boxes blindly.

**No legacy. No backwards compatibility.** Remove deprecated paths, `legacy_`* modules, compat shims, feature flags for old behaviour, dual “old vs new” implementations, and commented-out dead code. One way to do each thing. If something external truly needs a stable contract, version it explicitly — do not carry internal dual maintenance.

**UX and UI must be excellent.** If the interface is mediocre, confusing, or dated — fix it or **remake it entirely**. Setup flows, daily use, error states, mobile, visual polish, and information architecture all matter. “It works” is not enough; it should feel intentional and professional.

Do not stop at a report. **Implement. Verify. Loop.**

---

## Hard rules

1. **No subagents.** You do all exploration, research, coding, shell, and browser/testing work yourself.
2. **Do not stop until everything is done** (see above). Work as long as required.
3. **Research before you build.** For non-trivial decisions, do targeted web research first. Save notes with URLs under `.audit/.../research/`.
4. **Remake when justified.** Wrong foundation → redesign, don’t patch forever.
5. **Zero legacy / zero internal backcompat.** Delete old paths; update all call sites in the same change.
6. **Perfect UX/UI** for anything user-facing — polish or full remake.
7. **Full autonomy.** Reorganize, rename, delete, rewrite, redeploy, reset — your call. Document decisions in `.audit/`.
8. **Never commit secrets** to git.
9. **Commit locally as you go** with clear messages; **do not push** unless I explicitly ask.
10. **Discover project tooling** from README, configs, CI, and `--help`. Use what the project already has — do not assume a stack.

If a project-specific context file exists (e.g. `SPECTRA_PERFECTION_CONTEXT.md`), read it **after** this file and treat it as additional instructions for that repo.

---

## What to evaluate

Go through **everything** you find. Nothing is “out of scope” unless it truly cannot run in this environment.


| Area                 | Standard                                       | Remake OK?              |
| -------------------- | ---------------------------------------------- | ----------------------- |
| **Architecture**     | Clear, minimal concepts, no duplication        | Yes                     |
| **Code quality**     | No dead code, consistent patterns, good errors | Yes                     |
| **UI / UX**          | Modern, clear, accessible, mobile, polished    | **Yes — full remake**   |
| **API / interfaces** | Consistent, documented, good errors            | Yes                     |
| **Data layer**       | Sensible schema, performance, no redundant DBs | Yes                     |
| **Auth & security**  | Current best practices, no gaps                | Yes                     |
| **Performance**      | No obvious waste; measure improvements         | Yes                     |
| **Testing**          | Proves real behaviour; e2e where UI exists     | Yes — expand or rewrite |
| **CI / DX**          | Reproducible local dev; fix broken workflows   | Yes                     |
| **Docs**             | Accurate, sufficient for onboarding            | Yes — rewrite           |
| **Ops / deploy**     | Idempotent, observable                         | Yes                     |
| **Dependencies**     | Current, no CVEs, no unused packages           | Yes                     |


Research 4–8 comparable projects. Note what they do better.

---

## Progress tracking

Create `.audit/YYYY-MM-DD--<short-name>/` (gitignored — do not commit audit scratch unless I ask):

```
00-INDEX.md          # links to everything
progress.md          # living log + Definition of Done checkboxes
00-SCOPE.md          # what this project is (you write after bootstrap)
findings/            # audit issues with severity + evidence
research/            # web research notes + synthesis
verification/        # command output, test logs, screenshots refs
fixes/               # what you changed and why
plan/                # decisions, remakes, tradeoffs
```

Update `progress.md` after every major step. Track every Definition of Done checkbox yourself.

Core loop (repeat until done):

```
explore → research → decide → change → verify → find gaps → repeat
```

---

## Phase 0 — Bootstrap & map

1. Read README, CONTRIBUTING, agent guides, main configs, entrypoints.
2. `git status`, recent history, branch; integrate or discard partial prior work.
3. Discover and run all existing lint / format / typecheck / test / build commands.
4. Map architecture, data flow, auth, deploy, integrations, user-facing surfaces.
5. Write `00-SCOPE.md` — your understanding of the project (challenge whether structure is still optimal).
6. Fix broken CI/dev setup as you go; **local + live verification is the gate.**

---

## Phase 1 — Research (do this early)

Before big architectural or UI decisions:

- Best-in-class products in this domain
- Current patterns for this stack (check lockfile versions, upstream docs)
- Security, performance, UX benchmarks
- **Output:** `research/00-synthesis.md` — ranked improvements + “remake X” recommendations with evidence and URLs

---

## Phase 2 — Deep audit

Every layer. For each finding: severity, evidence (`file:line`), fix plan, status.

- Bugs · architecture · security · performance
- **UI/UX — every screen and flow you can find**
- Tests (do they prove behaviour or just exist?)
- Docs drift · dependencies · legacy/backcompat code to **delete**

Nothing gets a pass for “out of scope.” If you find it and it’s wrong, fix it.

---

## Phase 3 — Implement

**Write code. Ship changes.** No TODOs left for “later” unless blocked externally.

- Bug fixes (root cause, not band-aids)
- Optimizations (measure when possible)
- Reorganization / architecture cleanup
- **UI remake or polish to production quality**
- Remove **ALL** legacy/backcompat paths
- Security hardening
- Expand tests (unit → integration → e2e) — tests must prove real behaviour
- Fix CI/DX
- Update docs to match reality

Re-run relevant checks after each meaningful change. Rebuild/redeploy when the project requires it.

---

## Phase 4 — Verify (automated + live)

**You decide the exact commands** — discover them from the project. Typical categories:

- Lint / format / type checks
- Full test suite
- Build / packaging
- Deploy or run via the project’s own commands
- Smoke-test every critical path live

Log evidence to `.audit/.../verification/`. Full redeploy/reset is fine unless project context says otherwise.

---

## Phase 5 — Manual / browser verification

For any UI or human-facing flow — **do not skip**:

- Browser automation or hands-on testing for every page and primary flow
- Mobile viewport where relevant
- Auth, error states, empty states, loading states
- Console clean; no broken layouts
- CLI/API: exercise real commands and endpoints

`verification/manual-log.md` — every flow pass/fail with notes. If UX isn’t professional yet, go back to Phase 3.

---

## Phase 6 — Synthesis

`plan/01-improvement-plan.md` — what you researched, remade, deleted, and why. Update `00-INDEX.md`.

Only **external** blockers (hardware missing, third-party permanently down, missing credentials when none exist) may remain — not items you could fix.

---

## Definition of done

**Every applicable checkbox must be ✅ before you stop.** Track these in `progress.md`.

### Completion

- [ ] I have re-read my findings and nothing material is left open
- [ ] I would ship this to production without caveats
- [ ] Stale or superseded repo docs removed (wrong, outdated, or duplicated — including `docs/superpowers/` when no longer accurate); current wiki/README updated to match reality
- [ ] I have updated all relevant docs/wiki elements of this project

### Code & tests

- [ ] Lint / format / type checks clean (project’s own tools)
- [ ] All tests green; critical paths covered; e2e if UI exists
- [ ] Build / packaging succeeds
- [ ] Zero known unfixed bugs from my audit

### No legacy

- [ ] No `legacy_`*, `old_`*, compat shims, or dual code paths
- [ ] No dead code, stale feature flags, or “TODO remove when X” that should be done now
- [ ] One clear way to run, import, and configure each concern

### Quality & modernization

- [ ] Research synthesis with cited sources in `.audit/`
- [ ] Dependencies current or explicitly justified
- [ ] Architecture simplified where audit found bloat

### Security (if applicable)

- [ ] No secrets in source; findings resolved
- [ ] Sane defaults for auth, input validation, sandboxing
- [ ] Codebase thoroughly checked for possible security issues and concerns and fixed

### UX / UI (if applicable)

- [ ] Every page/flow tested in browser (or equivalent)
- [ ] UX is clear, polished, professional — not an afterthought
- [ ] Setup/onboarding works end-to-end
- [ ] Mobile acceptable where relevant

### Runtime

- [ ] App/service runs; all core and extra flows verified live
- [ ] Performance not regressed (or improved with evidence)

### Docs

- [ ] README and docs match current behaviour
- [ ] Fresh clone → dev setup works per project docs

**Any failure → back to Phase 3–5. Do not stop. Do not summarize and exit.**

---

## Start now

1. Create `.audit/YYYY-MM-DD--<short-name>/progress.md` with the full Definition of Done checklist
2. Bootstrap (Phase 0) → research (Phase 1) before big builds
3. Audit → implement → verify → loop until every checkbox is ✅
4. Make your own decisions; remake freely
5. Final summary to me **only when truly complete** — what changed, what you researched, evidence it works, honest external blockers only

