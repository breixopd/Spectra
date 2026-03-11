"""Arbitrary command and script execution jobs."""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.constants import GO_COMPILE_TIMEOUT

from .helpers import _run_command

logger = logging.getLogger("spectra.worker")


async def run_command_job(
    command: str,
    timeout: int = 300,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run an arbitrary shell command in the tools container."""
    logger.info("Running command: %s", command[:100])

    # Safety check: validate command against blocklists before execution
    from app.services.ai.agents.safety import SafetySupervisorAgent

    allowed, reason = SafetySupervisorAgent.check_blocklist(command)
    if not allowed:
        logger.warning("Command blocked by safety check: %s", reason)
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Blocked by safety check: {reason}",
        }

    wrapped = ["timeout", "-k", "10s", f"{timeout}s", "sh", "-c", command]
    returncode, stdout, stderr = await _run_command(wrapped, timeout + 30, cwd)

    return {
        "success": returncode == 0,
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


async def execute_script_job(
    content: str,
    language: str,
    target: str,
    args: list[str] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute a custom script (Python/Go/Bash)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"script_{timestamp}_{uuid.uuid4().hex[:4]}"
    work_dir = Path(f"/tmp/spectra_scripts/{run_id}")
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        if language.lower() in ("python", "python3"):
            script_path = work_dir / "exploit.py"
            script_path.write_text(content)
            cmd = ["python3", str(script_path), str(target)]

        elif language.lower() == "go":
            script_path = work_dir / "exploit.go"
            script_path.write_text(content)
            compile_cmd = ["go", "build", "-o", f"{work_dir}/exploit", str(script_path)]
            r_code, r_out, r_err = await _run_command(compile_cmd, GO_COMPILE_TIMEOUT, str(work_dir))
            if r_code != 0:
                return {
                    "success": False,
                    "exit_code": r_code,
                    "stdout": r_out,
                    "stderr": f"Compilation failed: {r_err}",
                }
            cmd = [f"{work_dir}/exploit", str(target)]

        elif language.lower() in ("bash", "sh"):
            script_path = work_dir / "exploit.sh"
            script_path.write_text(content)
            await _run_command(["chmod", "+x", str(script_path)], 5)
            cmd = [str(script_path), str(target)]

        else:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unsupported language: {language}",
            }

        if args:
            cmd.extend([str(arg) for arg in args])

        logger.info("Executing custom script (%s) against %s", language, target)

        wrapped = ["timeout", "-k", "10s", f"{timeout}s"] + cmd
        returncode, stdout, stderr = await _run_command(
            wrapped, timeout + 30, str(work_dir)
        )

        return {
            "success": returncode == 0,
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    except Exception as e:
        logger.error("Script execution failed: %s", e)
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }
    finally:
        try:
            shutil.rmtree(work_dir)
        except Exception as e:
            logger.debug("Cleanup failed: %s", e)
