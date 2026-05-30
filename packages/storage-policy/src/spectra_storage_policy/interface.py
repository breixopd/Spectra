"""Abstract interface for tiered storage.

Defines the contract that all tiered storage implementations must fulfill,
including the data model, tier enumeration, and async operations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class StorageTier(StrEnum):
    """Storage tiers supported by the tiered storage system."""

    HOT = "hot"
    COLD = "cold"


@dataclass
class StorageObject:
    """Metadata about a stored object.

    Attributes:
        key: Unique identifier for the object within the storage system.
        tier: Current storage tier (HOT or COLD).
        size_bytes: Size of the object in bytes.
        last_accessed: Unix timestamp of the last access.
        access_count: Cumulative number of accesses recorded.
    """

    key: str
    tier: StorageTier = StorageTier.HOT
    size_bytes: int = 0
    last_accessed: float = 0.0
    access_count: int = 0


class TieredStorage(ABC):
    """Abstract base class for tiered storage implementations.

    Implementations must handle two tiers (HOT and COLD) and provide
    auto-promotion on access so that frequently-used objects migrate
    to the hot tier automatically.
    """

    @abstractmethod
    async def put(
        self,
        key: str,
        data: bytes,
        metadata: dict | None = None,
        tier: StorageTier = StorageTier.HOT,
    ) -> None:
        """Store an object into the given tier (default HOT).

        Args:
            key: Object key.
            data: Raw bytes to store.
            metadata: Optional key-value metadata attached to the object.
            tier: Target storage tier.

        Raises:
            RuntimeError: If the underlying storage operation fails.
        """
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Retrieve an object, auto-promoting it to HOT on access.

        Returns:
            The raw bytes of the object, or None if the object does not exist.
        """
        ...

    @abstractmethod
    async def touch(self, key: str) -> None:
        """Record an access event to extend the object's TTL without
        downloading its content.
        """
        ...

    @abstractmethod
    async def promote(self, key: str) -> None:
        """Promote an object from COLD to HOT tier."""
        ...

    @abstractmethod
    async def demote(self, key: str) -> None:
        """Demote an object from HOT to COLD tier."""
        ...

    @abstractmethod
    async def get_tier_info(self, key: str) -> StorageObject | None:
        """Return metadata for the given object, or None if not found."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object from both tiers.

        Args:
            key: Object key to delete.
        """
        ...
