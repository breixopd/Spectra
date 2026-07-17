"""Per-mission ephemeral sandbox container management."""

from typing import Any

from spectra_tools.sandbox.golden_image import GoldenImageBuilder
from spectra_tools.sandbox.image_scanner import ImageScanner
from spectra_tools.sandbox.models import SandboxInfo
from spectra_tools.sandbox.pool import SandboxPool

__all__ = [
    "GoldenImageBuilder",
    "ImageScanner",
    "SandboxInfo",
    "SandboxPool",
    "get_image_builder",
    "get_sandbox_pool",
    "set_image_builder",
    "set_sandbox_pool",
]

_pool: Any | None = None
_image_builder: GoldenImageBuilder | None = None


def get_sandbox_pool() -> Any | None:
    """Get the global sandbox pool instance."""
    return _pool


def set_sandbox_pool(pool: Any | None) -> None:
    """Set the global sandbox pool instance. Called during app startup."""
    global _pool
    _pool = pool


def get_image_builder() -> GoldenImageBuilder | None:
    return _image_builder


def set_image_builder(builder: GoldenImageBuilder | None) -> None:
    global _image_builder
    _image_builder = builder
