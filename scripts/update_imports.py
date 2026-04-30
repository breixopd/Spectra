#!/usr/bin/env python3
"""Bulk-update all imports after moving app/core/ modules to new homes."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MOVE_MAP = {
    "cache": "app.infrastructure.cache",
    "queue": "app.infrastructure.queue",
    "events": "app.infrastructure.events",
    "tasks": "spectra_common.tasks",
    "redis_client": "app.infrastructure.redis_client",
    "background_tasks": "app.infrastructure.background_tasks",
    "system_status": "app.infrastructure.system_status",
    "metrics_store": "app.infrastructure.metrics_store",
    "circuit_breaker": "app.infrastructure.circuit_breaker",
    "paths": "spectra_common.paths",
    "security": "app.auth.security",
    "rbac": "spectra_api.authz",
    "encryption": "app.auth.encryption",
    "exceptions": "app.auth.exceptions",
    "advisory_locks": "app.auth.advisory_locks",
    "rate_limit": "app.auth.rate_limit",
    "lifespan": "spectra_api.bootstrap.lifespan",
    "middleware": "spectra_api.bootstrap.middleware",
    "logging_config": "spectra_api.bootstrap.logging_config",
    "templates": "spectra_api.templates",
    "state_machine": "app.mission.core.state_machine",
    "enums": "app.mission.core.enums",
    "websocket": "app.mission.core.websocket",
    "bridge": "app.mission.core.bridge",
    "optimizations": "app.mission.core.optimizations",
    "container": "app.di.container",
    "protocols": "app.di.protocols",
    "service_auth": "app.di.service_auth",
    "telemetry": "app.telemetry.telemetry",
    "telemetry_middleware": "spectra_api.telemetry_middleware",
}

OLD_TO_NEW = {f"app.core.{k}": v for k, v in MOVE_MAP.items()}

NEW_PARENT = {
    "cache": "app.infrastructure",
    "queue": "app.infrastructure",
    "events": "app.infrastructure",
    "tasks": "app.infrastructure",
    "redis_client": "app.infrastructure",
    "background_tasks": "app.infrastructure",
    "system_status": "app.infrastructure",
    "metrics_store": "app.infrastructure",
    "circuit_breaker": "app.infrastructure",
    "paths": "app.infrastructure",
    "security": "app.auth",
    "rbac": "app.auth",
    "encryption": "app.auth",
    "exceptions": "app.auth",
    "advisory_locks": "app.auth",
    "rate_limit": "app.auth",
    "lifespan": "spectra_api.bootstrap",
    "middleware": "spectra_api.bootstrap",
    "logging_config": "spectra_api.bootstrap",
    "templates": "spectra_api.bootstrap",
    "state_machine": "app.mission.core",
    "enums": "app.mission.core",
    "websocket": "app.mission.core",
    "bridge": "app.mission.core",
    "optimizations": "app.mission.core",
    "container": "app.di",
    "protocols": "app.di",
    "service_auth": "app.di",
    "telemetry": "app.telemetry",
    "telemetry_middleware": "app.telemetry",
}


def replace_imports(content: str) -> str:
    items = sorted(OLD_TO_NEW.items(), key=lambda x: len(x[0]), reverse=True)

    for old, new in items:
        module = old.split(".")[-1]
        content = re.sub(rf"from app\.core\.{module}\b", f"from {new}", content)

    for old, new in items:
        module = old.split(".")[-1]
        content = re.sub(rf"import app\.core\.{module}\b", f"import {new}", content)

    lines = content.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        m = re.match(r"^(\s*from\s+app\.core\s+import\s+)(.+)$", line)
        if m:
            prefix = m.group(1)
            rest = m.group(2)
            items_in_line = [x.strip() for x in rest.split(",")]
            all_moved = True
            parents = set()
            parsed_items = []
            for item in items_in_line:
                mod_name = item.split()[0]
                if mod_name in NEW_PARENT:
                    parents.add(NEW_PARENT[mod_name])
                    parsed_items.append((mod_name, item, True))
                else:
                    parsed_items.append((mod_name, item, False))
                    all_moved = False

            if all_moved and len(parents) == 1:
                parent = parents.pop()
                new_rest = ", ".join(items_in_line)
                line = f"{prefix.replace('app.core', parent)}{new_rest}\n"
            elif all_moved and len(parents) > 1:
                replacements = []
                for mod_name, item, _ in parsed_items:
                    parent = NEW_PARENT[mod_name]
                    replacements.append(f"from {parent} import {item}")
                line = "\n".join(replacements) + "\n"
            elif not all_moved:
                replacements = []
                kept = []
                for mod_name, item, is_moved in parsed_items:
                    if is_moved:
                        parent = NEW_PARENT[mod_name]
                        replacements.append(f"from {parent} import {item}")
                    else:
                        kept.append(item)
                if kept:
                    line = f"from app.core import {', '.join(kept)}\n"
                    if replacements:
                        line = "\n".join(replacements) + "\n" + line
                else:
                    line = "\n".join(replacements) + "\n"
        new_lines.append(line)
    content = "".join(new_lines)

    for old, new in items:
        content = re.sub(rf"\b{re.escape(old)}\b", new, content)

    return content


def process_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    new_text = replace_imports(text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"  updated {path}")


def main() -> None:
    for py_file in REPO.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        process_file(py_file)
    for md_file in REPO.rglob("*.md"):
        if "__pycache__" in md_file.parts:
            continue
        process_file(md_file)
    print("Done.")


if __name__ == "__main__":
    main()
