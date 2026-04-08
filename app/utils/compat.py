"""Python compatibility utilities."""

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    import enum

    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]  # noqa: UP042
        """String enum for Python < 3.11."""
