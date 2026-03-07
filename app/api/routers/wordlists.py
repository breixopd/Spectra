"""Wordlist Management API.

Endpoints for listing, uploading, and downloading wordlists
used by tools like gobuster, ffuf, hydra, etc.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.dependencies import get_current_active_user
from app.models.user import User

logger = logging.getLogger("spectra.api.wordlists")

router = APIRouter(prefix="/wordlists", tags=["Wordlists"])

WORDLISTS_DIR = Path("wordlists")

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
    """List available wordlists (local + downloadable presets)."""
    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)

    local: list[dict[str, Any]] = []
    for f in sorted(WORDLISTS_DIR.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            lines = 0
            try:
                with f.open("r", errors="ignore") as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                pass
            local.append({
                "name": f.stem.replace("-", " ").replace("_", " ").title(),
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "lines": lines,
                "path": str(f),
            })

    presets = []
    for key, preset in PRESET_WORDLISTS.items():
        downloaded = (WORDLISTS_DIR / f"{key}.txt").exists()
        presets.append({**preset, "id": key, "downloaded": downloaded})

    return {"local": local, "presets": presets}


@router.post("/upload")
async def upload_wordlist(
    file: UploadFile,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Upload a custom wordlist file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "-_.")
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = WORDLISTS_DIR / safe_name

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

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
    except Exception as e:
        logger.error("Failed to download preset %s: %s", preset_id, e)
        raise HTTPException(status_code=502, detail=f"Download failed: {e}") from e


@router.delete("/{filename}")
async def delete_wordlist(
    filename: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Delete a wordlist file."""
    safe_name = "".join(c for c in filename if c.isalnum() or c in "-_.")
    path = WORDLISTS_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Wordlist not found")

    path.unlink()
    return {"status": "deleted", "filename": safe_name}
