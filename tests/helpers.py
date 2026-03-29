"""Shared helpers for unit tests that patch module-level collaborators."""

from __future__ import annotations

import importlib
import types
from types import ModuleType
from typing import Any, TypeVar

ModuleT = TypeVar("ModuleT", bound=ModuleType)


def make_module(name: str, **attrs: object) -> ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def reload_module(module: ModuleT) -> ModuleT:
    return importlib.reload(module)


def has_async_update(async_mock: Any, item_id: str, **expected: object) -> bool:
    return any(
        call.args[0] == item_id
        and all(call.args[1].get(key) == value for key, value in expected.items())
        for call in async_mock.await_args_list
    )
