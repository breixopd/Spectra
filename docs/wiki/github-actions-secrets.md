# Secrets & tokens — full setup

[← Wiki Home](Home.md)

**I cannot generate or send you tokens.** GitHub shows each value **once** when you click **Generate**. You paste them into [repository secrets](https://github.com/breixopd/Spectra/settings/secrets/actions) yourself.

---

## Is fine-grained worth it if we still need classic?

**Yes**, for what fine-grained can do today:

| Credential | Scope | Why fine-grained wins |
|------------|--------|------------------------|
| Wiki + releases | **Only** repo `breixopd/Spectra`, **only** Contents | Classic `repo` would access **all** your repos |
| GHCR push in Actions | **`GITHUB_TOKEN`** per run | No stored PAT at all — expires with the job |
| VPS private image pull | Classic **`read:packages`** only | GitHub has **no** fine-grained Packages permission yet |

So you are not duplicating “full access” twice. You get **narrow** fine-grained tokens + **one minimal classic** (or **zero** classic if GHCR images are **public**).

**Most secure minimal set:**

1. One fine-grained token (wiki + releases) → `SPECTRA_ACTIONS_TOKEN`
2. No secret for GHCR push (Actions uses `GITHUB_TOKEN`)
3. **Either** public GHCR packages **or** one classic `read:packages` → `DEPLOY_GHCR_TOKEN`

---

## Step 1 — Fine-grained token(s)

Pick **one** approach.

### Option A — single token (recommended)

| After generate, paste into repo secret | |
|--------------------------------------|--|
| **`SPECTRA_ACTIONS_TOKEN`** | One fine-grained PAT |

**Prefilled link** (open while logged in as `breixopd`):

**[Create Spectra Actions token (fine-grained)](https://github.com/settings/personal-access-tokens/new?name=Spectra+Actions&description=Wiki+%2B+GitHub+releases+for+breixopd%2FSpectra&target_name=breixopd&contents=write&expires_in=90)**

On the page, confirm:

- Repository access: **Only select repositories** → **Spectra**
- Permissions: **Contents → Read and write**

Then **Generate token** → copy → [New repository secret](https://github.com/breixopd/Spectra/settings/secrets/actions/new) → name `SPECTRA_ACTIONS_TOKEN`.

### Option B — two tokens (smallest blast radius)

| Secret | Prefilled link |
|--------|----------------|
| **`SPECTRA_WIKI_TOKEN`** | [Create wiki token](https://github.com/settings/personal-access-tokens/new?name=Spectra+wiki+sync&description=Wiki+only+breixopd%2FSpectra&target_name=breixopd&contents=write&expires_in=90) |
| **`SPECTRA_RELEASE_TOKEN`** | [Create release token](https://github.com/settings/personal-access-tokens/new?name=Spectra+release&description=GitHub+releases+only+breixopd%2FSpectra&target_name=breixopd&contents=write&expires_in=90) |

Same permissions on both; separate tokens so you can revoke/rotate wiki without touching releases.

---

## Step 2 — GHCR push (CI) — **no PAT secret**

Release workflow logs into `ghcr.io` with the ephemeral **`GITHUB_TOKEN`** (`packages: write` on the job). **Do not create a secret for this.**

Images: `ghcr.io/breixopd/spectra-app`, `spectra-ai-svc`, `spectra-scheduler`, `spectra-worker`, `spectra-caddy`.

---

## Step 3 — VPS image pull (only if needed)

Skip entirely if you **build on the VPS** from git (`REGISTRY=` empty) or set packages **public**.

If the server must **`docker pull`** private images:

| Secret | Value |
|--------|--------|
| **`DEPLOY_GHCR_USERNAME`** | `breixopd` |
| **`DEPLOY_GHCR_TOKEN`** | Classic PAT, **`read:packages` only** |

**Prefilled classic link:**

**[Create VPS GHCR pull token (classic)](https://github.com/settings/tokens/new?description=Spectra+VPS+GHCR+pull+read-only&scopes=read:packages)**

- Do **not** enable `write:packages` unless you also push from the VPS manually.
- Expiration: 90 days (or your policy).

**Avoid public packages?** Alternative with **no classic token**: in GitHub → each package → **Package settings** → change visibility to **Public** (anonymous `docker pull` for GHCR public images).

---

## Step 4 — SSH deploy (optional)

Only if you use the **automated SSH deploy** job in `release.yml`. These are **not** GitHub PATs.

| Secret | How to get it |
|--------|----------------|
| **`DEPLOY_HOST`** | Your server IP or hostname |
| **`DEPLOY_USER`** | SSH user (`root`, `deploy`, …) |
| **`DEPLOY_SSH_KEY`** | Private key: `cat ~/.ssh/id_ed25519` (full PEM) |
| **`DEPLOY_SSH_HOST_FINGERPRINT`** | `ssh-keyscan -t ed25519 YOUR_HOST` → one line |
| **`DEPLOY_WEBHOOK_URL`** | Optional Discord/Slack webhook URL |

No prefilled link (these are your infrastructure values).

---

## Step 5 — VPS `.env` (not GitHub)

Set on the server, not in Actions secrets:

| Variable | Command / notes |
|----------|-----------------|
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `SERVICE_AUTH_SECRET` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | Strong random |
| `REDIS_PASSWORD` | Strong random |
| `GARAGE_*` / `S3_*` | See [Configuration](configuration.md) |
| `TENSORZERO_GATEWAY_URL` | Your gateway URL |

---

## Master checklist

Copy this and tick off:

```
GitHub Actions secrets (https://github.com/breixopd/Spectra/settings/secrets/actions)

Fine-grained (pick one approach):
[ ] SPECTRA_ACTIONS_TOKEN          ← Option A (one link above)
    OR
[ ] SPECTRA_WIKI_TOKEN             ← Option B wiki link
[ ] SPECTRA_RELEASE_TOKEN          ← Option B release link

GHCR push in CI:
[ ] (nothing — uses GITHUB_TOKEN automatically)

VPS pull (pick one):
[ ] Public GHCR packages — no DEPLOY_GHCR_TOKEN
    OR
[ ] DEPLOY_GHCR_USERNAME = breixopd
[ ] DEPLOY_GHCR_TOKEN    = classic read:packages (link above)

SSH deploy (optional):
[ ] DEPLOY_HOST
[ ] DEPLOY_USER
[ ] DEPLOY_SSH_KEY
[ ] DEPLOY_SSH_HOST_FINGERPRINT
[ ] DEPLOY_WEBHOOK_URL (optional)

VPS .env:
[ ] JWT_SECRET_KEY, SERVICE_AUTH_SECRET, DB passwords, Garage, LLM URL
```

---

## What each workflow reads

| Workflow | Secrets used |
|----------|----------------|
| **Sync wiki** | `SPECTRA_WIKI_TOKEN` → else `SPECTRA_ACTIONS_TOKEN` |
| **Release** (GHCR push) | `GITHUB_TOKEN` (built-in) |
| **Release** (GitHub Release) | `SPECTRA_RELEASE_TOKEN` → else `SPECTRA_ACTIONS_TOKEN` |
| **Release** (SSH deploy) | `DEPLOY_*` |
| **CI** | Mostly `GITHUB_TOKEN`; billing must be enabled |

---

## Security practices

- **Never** commit tokens to git or paste them in chat.
- Prefer **90-day expiry** on PATs; calendar a rotation reminder.
- Revoke old tokens when rotating.
- Use **Option B** (two fine-grained tokens) if you want wiki compromised without affecting release token.
- Prefer **public GHCR** or **local build on VPS** to avoid storing **any** classic PAT.

---

## Manual wiki push (uses fine-grained token)

```bash
git clone https://github.com/breixopd/Spectra.wiki.git
# When prompted for password, paste SPECTRA_WIKI_TOKEN or SPECTRA_ACTIONS_TOKEN
rsync -av --exclude='.git' /path/to/spectra/docs/wiki/ Spectra.wiki/
cd Spectra.wiki && git add -A && git commit -m "Sync docs/wiki" && git push
```
