# GitHub secrets (fine-grained first)

[← Wiki Home](Home.md)

Spectra uses **fine-grained personal access tokens** everywhere GitHub allows them. GHCR in Actions uses the built-in **`GITHUB_TOKEN`** (no stored PAT). The only exception is **pulling private images on a VPS**, which still needs a classic token until GitHub adds fine-grained Packages support.

---

## Tokens to create (fine-grained)

Create these under **Profile → Settings → Developer settings → Fine-grained personal access tokens**.

For each token:

| Field | Value |
|-------|--------|
| Resource owner | `breixopd` |
| Repository access | **Only select repositories** → **Spectra** |
| Repository permissions | **Contents: Read and write** |
| Metadata | Read-only (automatic) |

You will **not** see a **Packages** permission on fine-grained tokens for personal accounts — [GitHub documents this as a known limitation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations).

### 1. Wiki sync — `SPECTRA_WIKI_TOKEN`

| Repo secret name | Fine-grained token name (suggestion) |
|------------------|--------------------------------------|
| **`SPECTRA_WIKI_TOKEN`** | `Spectra wiki sync` |

**Permissions:** Contents read/write on **Spectra** only.

**Used by:** `.github/workflows/sync-wiki.yml`, manual `git push` to `Spectra.wiki.git`.

**Prefilled create link** (opens GitHub with fields set):

https://github.com/settings/personal-access-tokens/new?name=Spectra+wiki+sync&description=Wiki+sync+for+breixopd%2FSpectra&target_name=breixopd&contents=write

### 2. Releases — `SPECTRA_RELEASE_TOKEN`

| Repo secret name | Fine-grained token name (suggestion) |
|------------------|--------------------------------------|
| **`SPECTRA_RELEASE_TOKEN`** | `Spectra release` |

**Permissions:** Same as wiki — Contents read/write on **Spectra** only.

**Used by:** `softprops/action-gh-release` in `.github/workflows/release.yml`.

**Prefilled create link:**

https://github.com/settings/personal-access-tokens/new?name=Spectra+release&description=GitHub+releases+for+breixopd%2FSpectra&target_name=breixopd&contents=write

### Optional: one token instead of two

If you prefer a single fine-grained token, set **`SPECTRA_ACTIONS_TOKEN`** (Contents read/write) and leave `SPECTRA_WIKI_TOKEN` / `SPECTRA_RELEASE_TOKEN` unset — workflows fall back to `SPECTRA_ACTIONS_TOKEN`.

| Repo secret name | Covers |
|------------------|--------|
| **`SPECTRA_ACTIONS_TOKEN`** | Wiki + releases (combined) |

---

## GHCR (no fine-grained PAT stored)

| What | How |
|------|-----|
| **Push images** (release workflow on GitHub Actions) | Job permission `packages: write` + login with **`secrets.GITHUB_TOKEN`** |
| **Pull images** (your VPS / Swarm) | See [VPS pull token](#vps-pull-token-deploy_ghcr_token) below |

Do **not** put a fine-grained PAT in `docker login` for GHCR — it will not work.

---

## Repository secrets checklist

Add at **https://github.com/breixopd/Spectra/settings/secrets/actions**

### Fine-grained (create in UI)

| Secret | Required | Token permissions |
|--------|----------|-------------------|
| **`SPECTRA_WIKI_TOKEN`** | Yes (or use `SPECTRA_ACTIONS_TOKEN`) | Contents R/W on Spectra |
| **`SPECTRA_RELEASE_TOKEN`** | Yes (or use `SPECTRA_ACTIONS_TOKEN`) | Contents R/W on Spectra |
| **`SPECTRA_ACTIONS_TOKEN`** | Optional | Same; covers both if you use one token |

### Deploy (SSH + registry pull)

Only if the **release deploy** job pushes to your VPS over SSH:

| Secret | Type | What to enter |
|--------|------|----------------|
| **`DEPLOY_HOST`** | Host | IP or hostname |
| **`DEPLOY_USER`** | SSH | Linux user |
| **`DEPLOY_SSH_KEY`** | SSH key | Private key PEM (not a GitHub PAT) |
| **`DEPLOY_SSH_HOST_FINGERPRINT`** | SSH | Output of `ssh-keyscan -t ed25519 YOUR_HOST` |
| **`DEPLOY_GHCR_USERNAME`** | Registry | `breixopd` |
| **`DEPLOY_GHCR_TOKEN`** | See below | Pull token for the server |
| **`DEPLOY_WEBHOOK_URL`** | Optional | HTTPS webhook URL |

### VPS pull token (`DEPLOY_GHCR_TOKEN`)

GitHub **does not** support fine-grained PATs for Packages yet. Pick one:

| Approach | Security | Setup |
|----------|----------|--------|
| **A. Public GHCR images** | No pull secret on VPS | Set package visibility to public in GitHub Packages |
| **B. Classic read-only PAT** | Minimal classic scope | Classic token with **`read:packages`** only → `DEPLOY_GHCR_TOKEN` |
| **C. Same machine, local build** | No registry pull | Build images on VPS from git; skip `REGISTRY` |

There is no fine-grained equivalent today for option B — this is the **only** GitHub credential that may remain classic.

---

## Server `.env` (not GitHub Actions)

These are **not** GitHub tokens — set on the VPS in `.env`:

| Variable | Generate |
|----------|----------|
| `POSTGRES_PASSWORD` | Strong random |
| `REDIS_PASSWORD` | Strong random |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `SERVICE_AUTH_SECRET` | `openssl rand -hex 32` |
| `GARAGE_ACCESS_KEY` / `GARAGE_SECRET_KEY` / `GARAGE_RPC_SECRET` | Per [Configuration](configuration.md) |
| `TENSORZERO_GATEWAY_URL` | Your LLM gateway URL |
| Provider API keys | As needed |

---

## Summary diagram

```text
Fine-grained PAT (Contents R/W, Spectra only)
  ├── SPECTRA_WIKI_TOKEN    → wiki sync workflow
  └── SPECTRA_RELEASE_TOKEN → GitHub Release step

GITHUB_TOKEN (ephemeral, per workflow run)
  └── GHCR docker push in release job (packages: write)

Classic PAT (read:packages) — VPS only, if images are private
  └── DEPLOY_GHCR_TOKEN

SSH private key — VPS only
  └── DEPLOY_SSH_KEY
```

---

## After adding secrets

1. Fix **GitHub Actions billing** so workflows can run.
2. Run **Actions → Sync wiki** once, or push a change under `docs/wiki/`.
3. For releases: **Actions → Release** from `main` with a CalVer version.

---

## Manual wiki sync (no Actions)

```bash
git clone https://github.com/breixopd/Spectra.wiki.git
rsync -av --exclude='.git' /path/to/spectra/docs/wiki/ Spectra.wiki/
cd Spectra.wiki && git add -A && git commit -m "Sync docs/wiki" && git push
```

Use **`SPECTRA_WIKI_TOKEN`** when Git asks for a password.
