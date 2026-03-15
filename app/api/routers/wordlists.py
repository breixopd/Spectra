"""Wordlist Management API.

Endpoints for listing, uploading, and downloading wordlists
used by tools like gobuster, ffuf, hydra, etc.

System wordlists live in the shared ``wordlists/`` directory.
User wordlists live in ``wordlists/users/<user_id>/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import check_feature_allowed, get_current_active_user
from app.core.database import get_async_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wordlists", tags=["Wordlists"])

WORDLISTS_DIR = Path("wordlists")


def _user_wordlists_dir(user: User) -> Path:
    """Return the per-user wordlist directory."""
    d = WORDLISTS_DIR / "users" / str(user.id)
    d.mkdir(parents=True, exist_ok=True)
    return d


PRESET_WORDLISTS = {
    "common-web-paths": {
        "name": "Common Web Paths",
        "description": "Most common web directory and file paths (~4,600 entries)",
        "url": "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/common.txt",
        "category": "web",
        "tool_hint": "gobuster, ffuf, dirsearch, feroxbuster",
    },
    "top-usernames": {
        "name": "Top Usernames",
        "description": "Common usernames for brute-force testing (~8,900 entries)",
        "url": "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Usernames/top-usernames-shortlist.txt",
        "category": "auth",
        "tool_hint": "hydra",
    },
    "common-passwords": {
        "name": "Common Passwords",
        "description": "Top 1000 most common passwords",
        "url": "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/top-1000.txt",
        "category": "auth",
        "tool_hint": "hydra",
    },
    "subdomains-top5000": {
        "name": "Subdomains Top 5000",
        "description": "Top 5000 subdomains for DNS enumeration",
        "url": "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/DNS/subdomains-top1million-5000.txt",
        "category": "dns",
        "tool_hint": "subfinder, amass, gobuster dns",
    },
}


@router.get("")
async def list_wordlists(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """List available wordlists (system + user-owned + downloadable presets)."""
    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)

    # System wordlists (top-level files in wordlists/)
    system: list[dict[str, Any]] = []
    for f in sorted(WORDLISTS_DIR.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            lines = 0
            try:
                with f.open("r", errors="ignore") as fh:
                    lines = sum(1 for _ in fh)
            except (OSError, ValueError) as e:
                logger.debug("Failed to count wordlist lines: %s", e)
            system.append(
                {
                    "name": f.stem.replace("-", " ").replace("_", " ").title(),
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "lines": lines,
                    "path": str(f),
                    "scope": "system",
                }
            )

    # Per-user wordlists
    user_dir = _user_wordlists_dir(_current_user)
    user_local: list[dict[str, Any]] = []
    for f in sorted(user_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            lines = 0
            try:
                with f.open("r", errors="ignore") as fh:
                    lines = sum(1 for _ in fh)
            except (OSError, ValueError) as e:
                logger.debug("Failed to count wordlist lines: %s", e)
            user_local.append(
                {
                    "name": f.stem.replace("-", " ").replace("_", " ").title(),
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "lines": lines,
                    "path": str(f),
                    "scope": "user",
                }
            )

    presets = []
    for key, preset in PRESET_WORDLISTS.items():
        downloaded = (WORDLISTS_DIR / f"{key}.txt").exists()
        presets.append({**preset, "id": key, "downloaded": downloaded})

    return {"local": system + user_local, "system": system, "user": user_local, "presets": presets}


@router.post("/upload")
async def upload_wordlist(
    file: UploadFile,
    _current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    """Upload a custom wordlist file."""
    await check_feature_allowed(_current_user, session, "custom_wordlists")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "-_.")
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    user_dir = _user_wordlists_dir(_current_user)
    dest = user_dir / safe_name

    MAX_WORDLIST_SIZE = 50 * 1024 * 1024  # 50MB
    content = await file.read(MAX_WORDLIST_SIZE + 1)
    if len(content) > MAX_WORDLIST_SIZE:
        raise HTTPException(status_code=413, detail="Wordlist file too large (max 50MB)")

    dest.write_bytes(content)
    logger.info("Wordlist uploaded: %s (%d bytes)", safe_name, len(content))
    return {"status": "uploaded", "filename": safe_name}


@router.post("/download-preset/{preset_id}")
async def download_preset(
    preset_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Download a preset wordlist from SecLists."""
    if preset_id not in PRESET_WORDLISTS:
        raise HTTPException(status_code=404, detail="Preset not found")

    preset = PRESET_WORDLISTS[preset_id]
    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = WORDLISTS_DIR / f"{preset_id}.txt"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(preset["url"])
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("Downloaded preset wordlist: %s (%d bytes)", preset_id, len(resp.content))
            return {"status": "downloaded", "filename": f"{preset_id}.txt", "lines": resp.text.count("\n")}
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to download preset %s: %s", preset_id, e)
        raise HTTPException(status_code=502, detail=f"Download failed: {e}") from e


@router.delete("/{filename}")
async def delete_wordlist(
    filename: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Delete a wordlist file (user scope only; admins can delete system wordlists)."""
    safe_name = "".join(c for c in filename if c.isalnum() or c in "-_.")

    # Try user wordlist first
    user_dir = _user_wordlists_dir(_current_user)
    user_path = user_dir / safe_name
    if user_path.exists() and user_path.is_file():
        user_path.unlink()
        return {"status": "deleted", "filename": safe_name}

    # System wordlist — admin only
    sys_path = WORDLISTS_DIR / safe_name
    if sys_path.exists() and sys_path.is_file():
        if not _current_user.is_superuser:
            raise HTTPException(status_code=403, detail="Only admins can delete system wordlists")
        sys_path.unlink()
        return {"status": "deleted", "filename": safe_name}

    raise HTTPException(status_code=404, detail="Wordlist not found")
