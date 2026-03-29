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

logger = logging.getLogger(__name__)


def _job_result(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    return {
        "success": returncode == 0,
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _error_job_result(stderr: str, *, exit_code: int = -1, stdout: str = "") -> dict[str, Any]:
    return _job_result(exit_code, stdout, stderr)


def _wrap_shell_command(command: str, timeout: int) -> str:
    return f"timeout -k 10s {timeout}s {command}"


def _wrap_command_args(command: list[str], timeout: int) -> list[str]:
    return ["timeout", "-k", "10s", f"{timeout}s", *command]


async def _build_script_command(
    content: str,
    language: str,
    target: str,
    work_dir: Path,
) -> tuple[list[str] | None, dict[str, Any] | None]:
    normalized_language = language.lower()

    if normalized_language in ("python", "python3"):
        script_path = work_dir / "exploit.py"
        script_path.write_text(content)
        return ["python3", str(script_path), str(target)], None

    if normalized_language == "go":
        script_path = work_dir / "exploit.go"
        script_path.write_text(content)
        compile_cmd = ["go", "build", "-o", f"{work_dir}/exploit", str(script_path)]
        returncode, stdout, stderr = await _run_command(compile_cmd, GO_COMPILE_TIMEOUT, str(work_dir))
        if returncode != 0:
            return None, _error_job_result(
                f"Compilation failed: {stderr}",
                exit_code=returncode,
                stdout=stdout,
            )
        return [f"{work_dir}/exploit", str(target)], None

    if normalized_language in ("bash", "sh"):
        script_path = work_dir / "exploit.sh"
        script_path.write_text(content)
        await _run_command(["chmod", "+x", str(script_path)], 5)
        return [str(script_path), str(target)], None

    return None, _error_job_result(f"Unsupported language: {language}")


async def run_command_job(
    command: str,
    timeout: int = 300,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run an arbitrary shell command in the tools container."""
    logger.info("Running command: %s", command[:100])

    # Safety check: validate command against blocklists before execution
    from app.services.ai.agents.safety import SafetySupervisorAgent

    allowed, reason = SafetySupervisorAgent.check_blocklist(command)  # type: ignore[attr-defined]
    if not allowed:
        logger.warning("Command blocked by safety check: %s", reason)
        return _error_job_result(f"Blocked by safety check: {reason}")

    wrapped = _wrap_shell_command(command, timeout)
    returncode, stdout, stderr = await _run_command(wrapped, timeout + 30, cwd)

    return _job_result(returncode, stdout, stderr)


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
        cmd, error_result = await _build_script_command(content, language, target, work_dir)
        if error_result is not None:
            return error_result

        if args:
            cmd.extend([str(arg) for arg in args])

        logger.info("Executing custom script (%s) against %s", language, target)

        wrapped = _wrap_command_args(cmd, timeout)
        returncode, stdout, stderr = await _run_command(wrapped, timeout + 30, str(work_dir))

        return _job_result(returncode, stdout, stderr)

    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Script execution failed: %s", e)
        return _error_job_result(str(e))
    finally:
        try:
            shutil.rmtree(work_dir)
        except OSError as e:
            logger.debug("Cleanup failed: %s", e)
