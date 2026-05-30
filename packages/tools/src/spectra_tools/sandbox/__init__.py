"""Per-mission ephemeral sandbox container management."""

from spectra_tools.sandbox.golden_image import GoldenImageBuilder
from spectra_tools.sandbox.image_scanner import ImageScanner
from spectra_tools.sandbox.models import SandboxInfo
from spectra_tools.sandbox.pool import SandboxPool
from spectra_tools.sandbox.warm_pool import WarmPoolManager

__all__ = [
    "GoldenImageBuilder",
    "ImageScanner",
    "SandboxInfo",
    "SandboxPool",
    "WarmPoolManager",
    "get_image_builder",
    "get_sandbox_pool",
    "get_warm_pool_manager",
    "set_image_builder",
    "set_sandbox_pool",
    "set_warm_pool_manager",
]

_pool: SandboxPool | None = None
_warm_pool_manager: WarmPoolManager | None = None
_image_builder: GoldenImageBuilder | None = None


def get_sandbox_pool() -> SandboxPool | None:
    """Get the global sandbox pool instance."""
    return _pool


def set_sandbox_pool(pool: SandboxPool | None) -> None:
    """Set the global sandbox pool instance. Called during app startup."""
    global _pool
    _pool = pool


def get_warm_pool_manager() -> WarmPoolManager | None:
    return _warm_pool_manager


def set_warm_pool_manager(manager: WarmPoolManager | None) -> None:
    global _warm_pool_manager
    _warm_pool_manager = manager


def get_image_builder() -> GoldenImageBuilder | None:
    return _image_builder


def set_image_builder(builder: GoldenImageBuilder | None) -> None:
    global _image_builder
    _image_builder = builder
