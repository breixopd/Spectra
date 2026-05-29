"""Access-frequency-based promotion, demotion, and garbage-collection logic.

This module implements the core tiering policy: objects are promoted to
HOT when accessed frequently within a recent window, demoted to COLD
when their TTL expires without sufficient recent access, and eventually
garbage-collected from the COLD tier after an extended cold TTL.
"""

import time
from dataclasses import dataclass, field

from .interface import StorageTier


@dataclass
class PromotionConfig:
    """Configuration for auto-promotion based on access frequency.

    Attributes:
        access_count_threshold: Minimum number of accesses within the
            access window required to trigger promotion.
        access_window_seconds: Look-back window (in seconds) for counting
            recent accesses.
    """

    access_count_threshold: int = 3
    access_window_seconds: float = 3600.0


@dataclass
class TTLCalculator:
    """Determines when objects should be demoted or garbage-collected.

    Each access extends the effective TTL of an object.  Demotion
    moves an object from HOT to COLD; GC deletes it permanently.

    Attributes:
        base_ttl: Base time-to-live in seconds for the HOT tier.
        extension_factor: Multiplier applied to the base TTL per access
            (0 means no extension on access).
        cold_ttl: Time in seconds after which cold objects are eligible
            for garbage collection.
    """

    base_ttl: float = 86400.0 * 30  # 30 days
    extension_factor: float = 2.0
    cold_ttl: float = 86400.0 * 90  # 90 days

    def compute_ttl(self, access_count: int) -> float:
        """Compute effective TTL based on access count.

        TTL = base_ttl + base_ttl * access_count * extension_factor
        """
        return self.base_ttl + self.base_ttl * access_count * self.extension_factor

    def is_expired(self, last_access: float, access_count: int) -> bool:
        """Return True if the TTL for the given object has elapsed."""
        return (time.time() - last_access) > self.compute_ttl(access_count)

    def is_cold_expired(self, last_access: float) -> bool:
        """Return True if the cold-tier retention period has elapsed."""
        return (time.time() - last_access) > self.cold_ttl


def should_promote(
    access_count: int,
    last_access: float,
    config: PromotionConfig | None = None,
) -> bool:
    """Determine whether an object qualifies for promotion to HOT.

    Returns True when the access count within the configured window
    meets or exceeds the threshold AND the last access falls inside
    the window.
    """
    if config is None:
        config = PromotionConfig()
    if access_count < config.access_count_threshold:
        return False
    return (time.time() - last_access) <= config.access_window_seconds


def determine_tier(
    key: str,
    access_count: int,
    last_access: float,
    current_tier: StorageTier,
    promo_config: PromotionConfig | None = None,
    ttl_calc: TTLCalculator | None = None,
) -> StorageTier:
    """Evaluate the correct tier for an object given its access history.

    Args:
        key: Object identifier (unused by logic, available for logging).
        access_count: Cumulative accesses for this object.
        last_access: Timestamp of the most recent access.
        current_tier: The object's current storage tier.
        promo_config: Optional promotion configuration.
        ttl_calc: Optional TTL calculator.

    Returns:
        The recomputed StorageTier.
    """
    if promo_config is None:
        promo_config = PromotionConfig()
    if ttl_calc is None:
        ttl_calc = TTLCalculator()

    if should_promote(access_count, last_access, promo_config):
        return StorageTier.HOT

    if ttl_calc.is_expired(last_access, access_count):
        return StorageTier.COLD

    return current_tier


class GarbageCollector:
    """Scans the COLD tier and deletes objects past their cold TTL.

    Usage:
        gc = GarbageCollector(storage, ttl_calc)
        await gc.run()
    """

    def __init__(self, storage: "TieredStorage", ttl_calc: TTLCalculator | None = None):
        from .interface import TieredStorage  # avoid circular import at module level

        self._storage: TieredStorage = storage
        self._ttl: TTLCalculator = ttl_calc or TTLCalculator()

    async def run(self, keys: list[str]) -> list[str]:
        """Scan a list of COLD-tier keys and delete expired items.

        Args:
            keys: List of object keys to evaluate.

        Returns:
            List of keys that were deleted.
        """
        deleted: list[str] = []
        for key in keys:
            info = await self._storage.get_tier_info(key)
            if info is None:
                continue
            if info.tier != StorageTier.COLD:
                continue
            if self._ttl.is_cold_expired(info.last_accessed):
                await self._storage.delete(key)
                deleted.append(key)
        return deleted
