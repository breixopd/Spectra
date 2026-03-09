"""
Mission Demo Recorder.

Records tool execution steps as an asciinema-compatible cast file
for replay and sharing. Triggered when record_demo=True on mission start.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("spectra.mission.demo_recorder")


class DemoRecorder:
    """Records mission events as an asciinema-compatible cast file."""

    def __init__(self, mission_id: str, target: str):
        self.mission_id = mission_id
        self.target = target
        self.events: list[tuple[float, str, str]] = []  # (timestamp, type, data)
        self.start_time = time.time()
        self._recording = False

    def start(self) -> None:
        """Start recording."""
        self.start_time = time.time()
        self._recording = True
        self.add_output("\\r\\n\\033[1;35m=== Spectra Mission Recording ===\\033[0m\\r\\n")
        self.add_output(f"\\033[36mTarget:\\033[0m {self.target}\\r\\n")
        self.add_output(f"\\033[36mMission:\\033[0m {self.mission_id}\\r\\n\\r\\n")

    def stop(self) -> None:
        """Stop recording."""
        self.add_output("\\r\\n\\033[1;32m=== Mission Complete ===\\033[0m\\r\\n")
        self._recording = False

    def add_output(self, text: str) -> None:
        """Add output text to the recording."""
        if not self._recording and self.events:
            return
        elapsed = time.time() - self.start_time
        self.events.append((elapsed, "o", text))

    def record_tool_start(self, tool_id: str, target: str, args: dict) -> None:
        """Record a tool execution starting."""
        self.add_output(f"\\r\\n\\033[1;33m$ {tool_id}\\033[0m {target}\\r\\n")

    def record_tool_output(self, line: str) -> None:
        """Record a line of tool output."""
        self.add_output(line + "\\r\\n")

    def record_tool_result(self, tool_id: str, success: bool, findings: int) -> None:
        """Record tool completion."""
        status = "\\033[32m✓\\033[0m" if success else "\\033[31m✗\\033[0m"
        self.add_output(f"{status} {tool_id}: {'Success' if success else 'Failed'} ({findings} findings)\\r\\n")

    def record_finding(self, severity: str, title: str) -> None:
        """Record a finding discovery."""
        colors = {"critical": "31", "high": "33", "medium": "34", "low": "37", "info": "90"}
        color = colors.get(severity.lower(), "37")
        self.add_output(f"  \\033[{color}m[{severity.upper()}]\\033[0m {title}\\r\\n")

    def save(self) -> str | None:
        """Save recording as asciinema v2 cast file."""
        if not self.events:
            return None

        output_dir = Path("data/missions") / self.mission_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "demo.cast"

        header = {
            "version": 2,
            "width": 120,
            "height": 40,
            "timestamp": int(self.start_time),
            "title": f"Spectra Mission: {self.target}",
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
        }

        try:
            with open(output_path, "w") as f:
                f.write(json.dumps(header) + "\n")
                for ts, event_type, data in self.events:
                    f.write(json.dumps([round(ts, 6), event_type, data]) + "\n")

            logger.info("Demo recording saved: %s", output_path)
            return str(output_path)
        except Exception as e:
            logger.error("Failed to save demo: %s", e)
            return None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        return time.time() - self.start_time if self._recording else 0

    @property
    def event_count(self) -> int:
        return len(self.events)
