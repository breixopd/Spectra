"""Central import for PostgreSQL advisory locks (tests patch this module)."""

from app.auth.advisory_locks import advisory_lock_owner

__all__ = ["advisory_lock_owner"]
