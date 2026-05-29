# GitHub Actions secrets (fine-grained token)

[← About the wiki](about-the-wiki.md)

Use one **fine-grained personal access token** for automation that must push to GHCR, sync the wiki, and create releases. Store it as a repository secret:

| Secret name | Value |
|-------------|--------|
| **`SPECTRA_ACTIONS_TOKEN`** | Fine-grained PAT (see below) |

Workflows use `secrets.SPECTRA_ACTIONS_TOKEN` when set, and fall back to the built-in `GITHUB_TOKEN` otherwise.

## Create the token

1. GitHub → **Settings** (your profile) → **Developer settings** → **Fine-grained personal access tokens** → **Generate new token**.
2. **Resource owner:** `breixopd`
3. **Repository access:** **Only select repositories** → `Spectra`
4. **Repository permissions:**

| Permission | Access | Used for |
|------------|--------|----------|
| **Contents** | Read and write | Wiki sync (`.wiki.git`), release tags, changelog |
| **Metadata** | Read-only | Required (automatic) |
| **Packages** | Read and write | Push/pull `ghcr.io/breixopd/*` images on release |

5. **Expiration:** pick a rotation interval (e.g. 90 days); calendar a reminder to rotate.
6. Generate and copy the token once.

## Add the repository secret

1. **https://github.com/breixopd/Spectra/settings/secrets/actions**
2. **New repository secret**
3. Name: `SPECTRA_ACTIONS_TOKEN`
4. Value: paste the PAT

No prefix `ghp_` handling is needed—paste the token as-is.

## What uses this token

| Workflow | Step |
|----------|------|
| **Sync wiki** | Push `docs/wiki/` → `Spectra.wiki.git` |
| **Release** | `docker login ghcr.io`, `softprops/action-gh-release` |

GHCR login uses username **`breixopd`** (must match the token owner and image namespace `ghcr.io/breixopd/`).

## Deploy pulls (VPS / Swarm)

Image **pulls** on servers still use deploy secrets (separate from CI):

| Secret | Purpose |
|--------|---------|
| `DEPLOY_GHCR_USERNAME` | `breixopd` |
| `DEPLOY_GHCR_TOKEN` | PAT or classic token with **read:packages** (can be the same fine-grained token if it has Packages read) |

## After the first wiki sync

The placeholder page you created to enable the wiki can be **deleted** from the Wiki tab once **Sync wiki** has run successfully—`home.md` from the repo becomes the real home page. Extra orphan pages are not removed automatically by the sync job.

## Rotation

1. Generate a new fine-grained token with the same permissions.
2. Update `SPECTRA_ACTIONS_TOKEN` (and deploy pull token if shared).
3. Revoke the old token.
