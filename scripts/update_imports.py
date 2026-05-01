#!/usr/bin/env python3
"""Bulk-update imports after moving spectra_platform/core/ modules to new homes (legacy helper)."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MOVE_MAP = {
    "cache": "spectra_platform.infrastructure.cache",
    "queue": "spectra_platform.infrastructure.queue",
    "events": "spectra_platform.infrastructure.events",
    "tasks": "spectra_common.tasks",
    "redis_client": "spectra_platform.infrastructure.redis_client",
    "background_tasks": "spectra_platform.infrastructure.background_tasks",
    "system_status": "spectra_platform.infrastructure.system_status",
    "metrics_store": "spectra_platform.infrastructure.metrics_store",
    "circuit_breaker": "spectra_platform.infrastructure.circuit_breaker",
    "paths": "spectra_common.paths",
    "security": "spectra_platform.auth.security",
    "rbac": "spectra_api.authz",
    "encryption": "spectra_platform.auth.encryption",
    "exceptions": "spectra_common.errors",
    "advisory_locks": "spectra_common.advisory_locks",
    "rate_limit": "spectra_platform.auth.rate_limit",
    "lifespan": "spectra_api.bootstrap.lifespan",
    "middleware": "spectra_api.bootstrap.middleware",
    "logging_config": "spectra_api.bootstrap.logging_config",
    "templates": "spectra_api.templates",
    "state_machine": "spectra_platform.mission.core.state_machine",
    "enums": "spectra_platform.mission.core.enums",
    "websocket": "spectra_platform.mission.core.websocket",
    "bridge": "spectra_platform.mission.core.bridge",
    "optimizations": "spectra_platform.mission.core.optimizations",
    "container": "spectra_platform.di.container",
    "protocols": "spectra_platform.di.protocols",
    "service_auth": "spectra_platform.di.service_auth",
    "telemetry": "spectra_platform.telemetry.telemetry",
    "telemetry_middleware": "spectra_api.telemetry_middleware",
}

OLD_TO_NEW = {f"spectra_platform.core.{k}": v for k, v in MOVE_MAP.items()}

NEW_PARENT = {
    "cache": "spectra_platform.infrastructure",
    "queue": "spectra_platform.infrastructure",
    "events": "spectra_platform.infrastructure",
    "tasks": "spectra_platform.infrastructure",
    "redis_client": "spectra_platform.infrastructure",
    "background_tasks": "spectra_platform.infrastructure",
    "system_status": "spectra_platform.infrastructure",
    "metrics_store": "spectra_platform.infrastructure",
    "circuit_breaker": "spectra_platform.infrastructure",
    "paths": "spectra_platform.infrastructure",
    "security": "spectra_platform.auth",
    "rbac": "spectra_platform.auth",
    "encryption": "spectra_platform.auth",
    "exceptions": "spectra_platform.auth",
    "advisory_locks": "spectra_platform.auth",
    "rate_limit": "spectra_platform.auth",
    "lifespan": "spectra_api.bootstrap",
    "middleware": "spectra_api.bootstrap",
    "logging_config": "spectra_api.bootstrap",
    "templates": "spectra_api.bootstrap",
    "state_machine": "spectra_platform.mission.core",
    "enums": "spectra_platform.mission.core",
    "websocket": "spectra_platform.mission.core",
    "bridge": "spectra_platform.mission.core",
    "optimizations": "spectra_platform.mission.core",
    "container": "spectra_platform.di",
    "protocols": "spectra_platform.di",
    "service_auth": "spectra_platform.di",
    "telemetry": "spectra_platform.telemetry",
    "telemetry_middleware": "spectra_platform.telemetry",
}


def replace_imports(content: str) -> str:
    items = sorted(OLD_TO_NEW.items(), key=lambda x: len(x[0]), reverse=True)

    for old, new in items:
        module = old.split(".")[-1]
        content = re.sub(rf"from spectra_platform\.core\.{module}\b", f"from {new}", content)

    for old, new in items:
        module = old.split(".")[-1]
        content = re.sub(rf"import spectra_platform\.core\.{module}\b", f"import {new}", content)

    lines = content.splitlines(keepends=True)
    new_lines = []
    for line in lines:
        m = re.match(r"^(\s*from\s+spectra_platform\.core\s+import\s+)(.+)$", line)
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
                line = f"{prefix.replace('spectra_platform.core', parent)}{new_rest}\n"
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
                    line = f"from spectra_platform.core import {', '.join(kept)}\n"
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
