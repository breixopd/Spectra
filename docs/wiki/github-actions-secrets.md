# Secrets & tokens

[← Wiki Home](Home.md)

Tokens are created in your GitHub account settings and stored as **repository secrets** (Settings → Secrets and variables → Actions). Never commit token values to git.

---

## Fine-grained vs classic

| Task | Credential |
|------|------------|
| Wiki sync | Fine-grained PAT — **Contents** read/write on this repo only |
| GitHub Releases | Fine-grained PAT — same |
| Push container images (CI) | **`GITHUB_TOKEN`** in the workflow — no stored PAT |
| Pull private images on a server | Classic PAT with **`read:packages`**, *or* public packages, *or* build images locally |

Fine-grained tokens are still worth using: they limit access to **one repository** and **Contents** only. Classic `repo` would expose every repository you can access. The optional classic token is **only** for registry pull on a host GitHub Actions does not control.

---

## Fine-grained tokens (Option B)

Create two tokens (or one combined `SPECTRA_ACTIONS_TOKEN` if you prefer).

**For each token:**

- Resource owner: your account (or org that owns the repo)
- Repository access: **only this repository**
- Permission: **Contents → Read and write**

| Repository secret | Purpose |
|-------------------|---------|
| **`SPECTRA_WIKI_TOKEN`** | Wiki sync workflow, manual push to `<repo>.wiki.git` |
| **`SPECTRA_RELEASE_TOKEN`** | Creating GitHub Releases |

Optional combined secret:

| **`SPECTRA_ACTIONS_TOKEN`** | Wiki + releases if you use one token for both |

---

## Container images (GHCR) — push

**No PAT secret is required to upload images from Actions.**

The **Release** workflow (`workflow_dispatch` on `main`) builds service images and pushes them to:

`ghcr.io/<repository-owner>/spectra-app` (and `spectra-ai-svc`, `spectra-scheduler`, `spectra-worker`, `spectra-caddy`)

Login uses the job’s built-in **`GITHUB_TOKEN`** (`packages: write`). That is not a fine-grained or classic PAT you store in secrets.

**When billing is enabled:**

- **Release** must be started manually: Actions → **Release** → Run workflow → enter a CalVer version (e.g. `2026.05.29`).
- Leave **Deploy to production** unchecked when you do not have a server; images and package assets still publish.
- Pushing to `main` alone does **not** publish container images; it runs **CI** (tests, static analysis, etc.).

---

## Python package artifacts

GitHub does **not** offer a PyPI-compatible package registry for Python wheels. The repo therefore publishes Python packages as **GitHub Release assets**:

- The **Release** workflow builds wheels/sdists for workspace packages under `packages/` (for example `spectra_common`, `spectra_domain`, `spectra_persistence`, `spectra_mission`, `spectra_tools_core`, `spectra_storage_policy`, and the other bounded libraries).
- Those files are attached to the GitHub Release alongside the changelog.
- CI on `main` also builds the same package files and uploads them as workflow artifacts for verification, but CI does not publish them as a public package registry.

---

## GHCR pull token — where to save it

Depends how you deploy.

### A. Automated deploy (Release workflow → SSH to VPS)

Store in **repository Actions secrets** (same place as `SPECTRA_WIKI_TOKEN`):

| Secret | Value |
|--------|--------|
| **`DEPLOY_GHCR_USERNAME`** | GitHub username that owns the packages |
| **`DEPLOY_GHCR_TOKEN`** | Classic PAT with **`read:packages`** only |

The deploy job SSHs to your server and runs `docker login ghcr.io` there using these values. You do **not** put this token in the server `.env` for that path.

Also required for automated deploy: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_SSH_HOST_FINGERPRINT`. Optional: `DEPLOY_WEBHOOK_URL`.

The Release workflow has a **Deploy to production** checkbox. Keep it unchecked until these secrets exist.

### B. Manual deploy on the VPS (you run compose/swarm yourself)

**Not** in repository secrets unless you later use automated deploy.

On the server, once per machine (or when the token rotates):

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME -p YOUR_CLASSIC_READ_PACKAGES_TOKEN
```

Credentials are stored in `~/.docker/config.json`. Then set in `.env`:

```bash
REGISTRY=ghcr.io/YOUR_GITHUB_USERNAME/
VERSION=2026.05.29   # tag from the Release you pulled
```

### C. No classic token

- Set GHCR package visibility to **public**, or  
- Leave `REGISTRY=` empty and **build images locally** on the VPS from the git checkout (`docker compose build`).

---

## CI package verification on push to `main`

CI includes a **Build package artifacts** job on pushes to `main`. It builds wheels/sdists and uploads them as CI artifacts. It does **not** publish to PyPI or a GitHub package registry.

---

## VPS `.env` (application secrets)

These are **not** GitHub PATs — generate on the server:

| Variable | Notes |
|----------|--------|
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `SERVICE_AUTH_SECRET` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | Strong random |
| `GARAGE_*` / `S3_*` | See [Configuration](configuration.md) |
| `TENSORZERO_GATEWAY_URL` | LLM gateway |

---

## Checklist (Option B + private GHCR pull)

```
Repository Actions secrets:
[ ] SPECTRA_WIKI_TOKEN
[ ] SPECTRA_RELEASE_TOKEN
[ ] (none for GHCR push — automatic in Release job)

If automated SSH deploy:
[ ] DEPLOY_GHCR_USERNAME
[ ] DEPLOY_GHCR_TOKEN
[ ] DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_SSH_HOST_FINGERPRINT

If manual VPS deploy with private images:
[ ] docker login on the VPS (not in .env)
[ ] REGISTRY + VERSION in .env

VPS application .env:
[ ] JWT, SERVICE_AUTH_SECRET, DB, storage, LLM URL
```

---

## Manual wiki sync

```bash
git clone https://github.com/<owner>/<repo>.wiki.git
rsync -av --exclude='.git' /path/to/<repo>/docs/wiki/ <repo>.wiki/
cd <repo>.wiki && git add -A && git commit -m "Sync docs/wiki" && git push
```

Use `SPECTRA_WIKI_TOKEN` as the password when Git prompts.
