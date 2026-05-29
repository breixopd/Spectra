# About this documentation

[← Wiki Home](home.md)

Spectra keeps **operator and developer docs in the repository** under `docs/wiki/`. That folder is the source of truth: it is reviewed in pull requests, versioned with releases, and linked from the root [README](https://github.com/breixopd/Spectra/blob/main/README.md).

## GitHub Wiki tab (optional reader UI)

The repository also has the **GitHub Wiki** feature enabled. A workflow (`.github/workflows/sync-wiki.yml`) mirrors `docs/wiki/` into the wiki Git repo (`breixopd/Spectra.wiki.git`) whenever `main` changes, so the Wiki tab stays aligned with the tree without maintaining two copies by hand.

### One-time setup (repo admin)

1. Open **https://github.com/breixopd/Spectra/wiki** and create any first page once (enables `.wiki.git`). You can delete that placeholder after the first successful sync.
2. Add repository secret **`SPECTRA_ACTIONS_TOKEN`** — see [GitHub Actions secrets](github-actions-secrets.md).
3. Push to `main` (or run **Actions → Sync wiki → Run workflow**).
4. Confirm wiki pages match `docs/wiki/` and that `_Sidebar.md` renders as the left nav.

### What syncs and what does not

| In repo | On GitHub Wiki |
|-------|----------------|
| All `docs/wiki/*.md` | Yes |
| `docs/wiki/_Sidebar.md` | Yes (wiki sidebar) |
| `docs/runbooks/` | **No** — see [Runbooks](runbooks.md) for links into the main repo |
| `docs/contributing/` | **No** — use [CONTRIBUTING](https://github.com/breixopd/Spectra/blob/main/CONTRIBUTING.md) |

Wiki pages must not use `../runbooks/` links (those paths do not exist in the wiki repo). Use [Runbooks](runbooks.md) or full `github.com/breixopd/Spectra/blob/main/…` URLs instead.

### Editing workflow

1. Change markdown under `docs/wiki/` in a branch.
2. Open a PR; reviewers see the same diff as code.
3. After merge to `main`, the sync workflow updates the GitHub Wiki automatically.

To edit only via the GitHub Wiki UI, clone the wiki repo locally:

```bash
git clone https://github.com/breixopd/Spectra.wiki.git
# edit, commit, push — then backport changes into docs/wiki/ or they will be overwritten on the next sync
```

**Recommendation:** treat `docs/wiki/` as canonical; use the Wiki tab as a rendered mirror for browsing.

## Container images (GHCR)

Release images are published to **`ghcr.io/breixopd/`** (account matches the repository owner). Swarm defaults use `REGISTRY=ghcr.io/breixopd/`. CI uses `SPECTRA_ACTIONS_TOKEN`; deploy pulls use `DEPLOY_GHCR_USERNAME` / `DEPLOY_GHCR_TOKEN` — see [GitHub Actions secrets](github-actions-secrets.md).
