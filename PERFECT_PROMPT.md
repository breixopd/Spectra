# Perfection Run — Master Prompt

Generic instruction set for long-horizon “make it production-ready” work. Pair with a **project shim** (e.g. `SPECTRA_FABLE_SHIM.md`) for repo-specific paths, stack, and audit targets.

**Audit folder:** `.audit/YYYY-MM-DD--<project>/` — log research, decisions, verification, and a `progress.md` checklist.

---

## Principles

1. **Finish the job** — Do not stop at a plan or partial implementation. Ship working code, tests, and docs. Take as long as needed.
2. **No legacy / no internal backwards compat** — Not public or no users yet? Delete old paths in the same change. One way to do things. No permanent feature flags for invariant behaviour. No `legacy_*`, `old_*`, or compat shims.
3. **Research before keeping** — Verify against current docs, similar products, and tests. If something should go, remove it.
4. **Decide autonomously** — Pick the option that simplifies and future-proofs. Do not ask unless the choice is irreversible or costly.
5. **Quality over speed** — Clean, idiomatic code matching project conventions. Minimal scope per change. No over-engineering.
6. **Secrets never in source** — Use env, secret stores, or gitignored config. Never commit credentials.
7. **Repo hygiene** — Respect `.gitignore`. Test/runtime data stays in volumes or temp dirs, not committed host paths.
8. **Commit locally as you go; do not push** unless explicitly asked.

---

## Phase 0 — Bootstrap

1. Read `README.md`, primary config, and `docs/` (wiki or equivalent).
2. Map the tree: services, packages, deploy, scripts, tests.
3. If a project shim exists, read it now.
4. Create `.audit/YYYY-MM-DD--<project>/progress.md` with the Definition of Done below.
5. Run project quality gates (adapt commands to the stack):

```bash
# Examples — replace with this repo's real commands
<install-deps>          # e.g. uv sync, pip install -e ".[test]", npm ci
<lint>                  # e.g. ruff check ., eslint
<unit-tests>            # e.g. pytest tests/unit/ -q
<build>                 # e.g. docker compose config, npm run build
```

Fix broken CI/workflows as part of the run, but **gate on local lint + tests + live deploy**, not green CI alone.

---

## Phase 1 — Research

Before large changes, briefly research:

- Comparable open-source or commercial products — what do they do better?
- Current best practices, security advisories, and library/docs for your stack
- Whether existing code should be **kept, narrowed, or deleted**

Record keep/cut decisions in `.audit/.../research.md`.

---

## Phase 2 — Audit

Systematically review the codebase and docs. At minimum:

| Area | Questions |
|------|-----------|
| **Architecture** | Clear boundaries? Dead modules? Cyclic deps? One deploy path? |
| **Security** | Auth, secrets, CSRF/CSP, inter-service trust, least privilege |
| **Data** | Migrations clean? Single head? Backup/restore story? |
| **API & contracts** | Consistent schemas? Unused endpoints? |
| **UI/UX** | Every user flow works? Mobile/responsive? Loading/error states? |
| **Admin / ops** | Can operators manage the full platform from admin tools? |
| **Deploy & scale** | Idempotent setup? Multi-node/orchestration if applicable? Self-healing? |
| **Tests** | Meaningful coverage? Flakes? Integration gaps? |
| **Docs** | Wiki/README match reality? |
| **Legacy** | Duplicate implementations, shims, stale flags to delete |

Expand the table in the project shim with product-specific surfaces (billing, training, etc.).

---

## Phase 3 — Implement

- Fix bugs and wire dormant systems; **remove** what has no benefit.
- Prefer refactors that shrink surface area over adding layers.
- Update all call sites in the same change when removing a path.
- Add or fix tests for real behaviour — not trivia.
- Keep docs in sync with behaviour changes.

---

## Phase 4 — Live verification

Deploy or use the existing environment. Verify:

- Health endpoints and critical dependencies
- Bootstrap/first-run and upgrade paths (idempotent)
- End-to-end flows operators and users actually run
- Logs: no unexpected errors under normal use

Log commands, outputs, and failures to `.audit/.../verification/`.

---

## Phase 5 — Browser & UX verification

Use **cursor-ide-browser MCP** (or equivalent) when the product has a web UI.

For each route/surface in the project shim:

1. Page loads (no blank shell forever)
2. Auth/session works where required
3. Core smoke action succeeds
4. No critical console errors
5. Layout acceptable on desktop; check mobile for primary flows

Record per-URL results in `.audit/.../verification/browser-log.md`.

---

## Definition of Done

All must pass before you stop:

### Code & architecture
- [ ] No known legacy dual paths or internal compat shims left behind
- [ ] Lint and unit tests pass locally
- [ ] Import/architecture boundaries respected (if the project enforces them)
- [ ] Migrations apply cleanly (if applicable)

### Deploy & runtime
- [ ] Automated setup/deploy path works idempotently
- [ ] Stack comes up healthy; self-healing/maintenance behaves as designed
- [ ] Multi-node / scaling scenarios verified if the product supports them

### Product
- [ ] Primary user flows work end-to-end (see project shim)
- [ ] Admin/operator can manage configured platform surfaces (including models/settings if applicable)
- [ ] Public/marketing and authenticated app surfaces both correct (SSR vs SPA hybrid if used)

### Quality
- [ ] No test artifacts or runtime data committed or left on host against `.gitignore`
- [ ] Docs/wiki updated for changed behaviour
- [ ] Browser matrix complete for all listed UI routes

### Process
- [ ] `progress.md` checklist fully checked
- [ ] Local commits made; not pushed unless asked

---

## Agent behaviour

- **Do not use subagents** when the project shim says to work directly.
- **Do not ask the user questions** for decisions you can make from code and research.
- **Proactive discovery** — if you find one bug or anti-pattern, check for the same elsewhere.
- **Remake is allowed** — if research shows a full UI or subsystem rewrite is cleaner than patching, do it (still no legacy left behind).

---

## Start

1. Read this file + the project shim (if any)
2. Create `.audit/YYYY-MM-DD--<project>/progress.md` with the DoD above plus shim-specific items
3. Execute Phases 0–5
4. **Do not stop until everything is done**
