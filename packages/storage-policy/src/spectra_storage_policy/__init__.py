"""Standalone tiered storage module.

Provides hot/cold tiering for S3-compatible storage with auto-promotion
based on access frequency.
"""

from .garage import GarageTieredStorage
from .interface import StorageObject, StorageTier, TieredStorage
from .metrics import MetricsCollector
from .policy import GarbageCollector, PromotionConfig, TTLCalculator, determine_tier
from .s3_native import S3TieredStorage

__all__ = [
    "GarageTieredStorage",
    "GarbageCollector",
    "MetricsCollector",
    "PromotionConfig",
    "S3TieredStorage",
    "StorageObject",
    "StorageTier",
    "TTLCalculator",
    "TieredStorage",
    "determine_tier",
]
