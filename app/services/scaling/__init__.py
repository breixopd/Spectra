"""Multi-server scaling and pool management."""

from app.services.scaling.pool_manager import ServerPoolManager, get_pool_manager

__all__ = ["ServerPoolManager", "get_pool_manager"]

# AutoScaler is imported lazily where needed to avoid pulling in subprocess at module load.
