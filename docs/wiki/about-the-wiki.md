# About this documentation

[← Wiki Home](Home.md)

Spectra keeps **operator and developer docs in the repository** under `docs/wiki/`. That folder is the source of truth: it is reviewed in pull requests, versioned with releases, and linked from the root README.

## GitHub Wiki tab (optional reader UI)

The repository can mirror `docs/wiki/` into the GitHub Wiki git repo (`<repo>.wiki.git`) via `.github/workflows/sync-wiki.yml` when Actions runs.

### One-time setup (repo admin)

1. Enable the Wiki tab and create any first page once (provisions `.wiki.git`). Delete the placeholder after the first real sync.
2. Add the fine-grained **`SPECTRA_WIKI_TOKEN`** only when wiki synchronization is required — see [GitHub secrets](github-actions-secrets.md).
3. Push to `main` or run **Actions → Sync wiki** when billing allows.
4. Confirm pages match `docs/wiki/` and `_Sidebar.md` renders as the nav.

### What syncs and what does not

| In repo | On GitHub Wiki |
|-------|----------------|
| All `docs/wiki/*.md` | Yes |
| `docs/wiki/_Sidebar.md` | Yes (wiki sidebar) |
| `docs/runbooks/` | **No** — see [Runbooks](runbooks.md) for links into the main repo |
| `docs/contributing/` | **No** — link to `CONTRIBUTING.md` in the main repo |

Wiki pages must not use `../runbooks/` links (those paths do not exist in the wiki repo). Use [Runbooks](runbooks.md) or absolute links to files on the default branch.

### Editing workflow

1. Change markdown under `docs/wiki/` in a branch.
2. Open a PR; reviewers see the same diff as code.
3. After merge to `main`, the sync workflow updates the GitHub Wiki automatically.

To edit only via the GitHub Wiki UI, clone the wiki repo locally:

```bash
git clone https://github.com/<owner>/<repo>.wiki.git
# edit, commit, push — then backport changes into docs/wiki/ or they will be overwritten on the next sync
```

**Recommendation:** treat `docs/wiki/` as canonical; use the Wiki tab as a rendered mirror for browsing.

## Container images (GHCR)

Release images are published to **`ghcr.io/<repository-owner>/`**. Image push in CI uses **`GITHUB_TOKEN`**; wiki/releases use fine-grained PATs — see [GitHub secrets](github-actions-secrets.md).
