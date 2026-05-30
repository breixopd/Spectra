"""Central import for PostgreSQL advisory locks (tests patch this module)."""

from spectra_persistence.advisory_locks import advisory_lock_owner

__all__ = ["advisory_lock_owner"]
