# GitHub Actions & deploy secrets

[← Wiki Home](Home.md)

Everything you need to configure in **GitHub → Spectra → Settings → Secrets and variables → Actions**, plus what goes on the server in `.env` (not GitHub).

---

## Required for CI (minimum)

| Secret | Required? | What to put |
|--------|-----------|-------------|
| **`SPECTRA_ACTIONS_TOKEN`** | Recommended | See [Fine-grained token](#fine-grained-token-wiki--releases) below |

If this secret is **missing**, workflows fall back to the built-in `GITHUB_TOKEN` (works for wiki/releases only when Actions billing is enabled and default permissions allow it).

---

## Fine-grained token (wiki + releases)

Use when Actions billing is fixed, or for manual `git push` to `Spectra.wiki.git`.

1. Profile **Settings → Developer settings → Fine-grained personal access tokens → Generate**.
2. **Resource owner:** `breixopd`
3. **Repository access:** Only **Spectra**
4. **Repository permissions** (this is the only dropdown section for repo-scoped tokens):

| Permission | Access |
|------------|--------|
| **Contents** | Read and write |
| **Metadata** | Read-only (auto) |

There is often **no “Packages” row** on fine-grained tokens for personal accounts, or GHCR still expects a **classic** token for `docker push`. That is normal.

5. Create token → copy once → add as repo secret **`SPECTRA_ACTIONS_TOKEN`**.

**Used for:** wiki sync workflow, GitHub Release creation, git operations in release job.

---

## GHCR / container images (classic token)

For **`docker push`** to `ghcr.io/breixopd/*` on release, use a **classic** PAT:

1. **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate**.
2. Scopes:
   - **`write:packages`** (includes read)
   - **`read:org`** only if you later use an org-owned registry
3. Store as **`SPECTRA_GHCR_TOKEN`** (add this secret name to the repo).

| Secret | Value |
|--------|--------|
| **`SPECTRA_GHCR_TOKEN`** | Classic PAT with `write:packages` |

Release workflow today uses `SPECTRA_ACTIONS_TOKEN` for GHCR login. After you add `SPECTRA_GHCR_TOKEN`, wire it in `release.yml` or use the **same classic token** as `SPECTRA_ACTIONS_TOKEN` only for release (Contents still need fine-grained or classic `repo` scope).

**Practical approach:** one **classic** token with scopes **`repo`** + **`write:packages`** as `SPECTRA_ACTIONS_TOKEN` covers wiki (via repo access), releases, and GHCR until fine-grained Packages is available in your UI.

| Classic scope | Purpose |
|---------------|---------|
| `repo` | Wiki git, tags, releases |
| `write:packages` | Push/pull `ghcr.io/breixopd/*` |

Username for `docker login` is always **`breixopd`**.

---

## Release deploy job (only when you use automated SSH deploy)

These are required only if the **deploy** job in `release.yml` runs against your VPS:

| Secret | Example / notes |
|--------|------------------|
| **`DEPLOY_HOST`** | VPS hostname or IP |
| **`DEPLOY_USER`** | SSH user (e.g. `root` or `deploy`) |
| **`DEPLOY_SSH_KEY`** | Private key (full PEM, including `-----BEGIN...`) |
| **`DEPLOY_SSH_HOST_FINGERPRINT`** | `ssh-keyscan` host key fingerprint |
| **`DEPLOY_GHCR_USERNAME`** | `breixopd` |
| **`DEPLOY_GHCR_TOKEN`** | Classic PAT with **`read:packages`** (pull images on server) |
| **`DEPLOY_WEBHOOK_URL`** | Optional — POST after deploy (Slack/Discord webhook) |

Skip these if you deploy manually on the VPS with `docker compose` / Swarm.

---

## Server `.env` (not GitHub Actions secrets)

Set on the machine running Spectra (see [Configuration](configuration.md)):

| Variable | Notes |
|----------|--------|
| `POSTGRES_PASSWORD` | DB password |
| `REDIS_PASSWORD` | Redis |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `SERVICE_AUTH_SECRET` | `openssl rand -hex 32` |
| `GARAGE_ACCESS_KEY` / `GARAGE_SECRET_KEY` / `GARAGE_RPC_SECRET` | Object storage |
| `TENSORZERO_GATEWAY_URL` | LLM gateway |
| `OPENAI_API_KEY` / others | As needed |

---

## Wiki without Actions billing

You do **not** need a secret or Actions minutes to publish the wiki:

```bash
git clone https://github.com/breixopd/Spectra.wiki.git
rsync -av --exclude='.git' /path/to/spectra/docs/wiki/ Spectra.wiki/
cd Spectra.wiki && git add -A && git commit -m "Sync docs/wiki" && git push
```

Use a fine-grained PAT with **Contents: write** when Git prompts for credentials. The live wiki is at **https://github.com/breixopd/Spectra/wiki** (home page: **Home**).

---

## Quick checklist

- [ ] `SPECTRA_ACTIONS_TOKEN` — fine-grained **Contents** read/write, *or* classic `repo` + `write:packages`
- [ ] `DEPLOY_*` — only if using release SSH deploy
- [ ] VPS `.env` — production secrets
- [ ] Fix **GitHub Actions billing** before relying on automated wiki sync / CI
