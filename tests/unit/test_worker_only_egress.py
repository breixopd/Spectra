"""Tests for worker-only target network boundaries."""

from __future__ import annotations

from pathlib import Path

COMPOSE_TEST = Path(__file__).resolve().parents[2] / "deploy" / "docker" / "compose.yaml"


def _service_block(text: str, service: str) -> str:
    marker = f"  {service}:\n"
    start = text.index(marker)
    next_service = text.find("\n  ", start + len(marker))
    while next_service != -1 and text[next_service + 3 : next_service + 4] == " ":
        next_service = text.find("\n  ", next_service + 1)
    return text[start:] if next_service == -1 else text[start:next_service]


def test_api_services_are_not_attached_to_target_network():
    text = COMPOSE_TEST.read_text(encoding="utf-8")

    for service in ("app", "app-replica"):
        block = _service_block(text, service)
        assert "targets:" not in block


def test_vulnerable_targets_are_isolated_from_backend_network():
    text = COMPOSE_TEST.read_text(encoding="utf-8")

    for service in ("metasploitable", "dvwa"):
        block = _service_block(text, service)
        assert "backend:" not in block
