"""
User Repository for managing user accounts.

Provides data access operations for user authentication and management.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    Repository for User entity operations.

    Provides specialized queries for user authentication and management.
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the user repository.

        Args:
            session: Async database session.
        """
        super().__init__(User, session)

    async def get_by_username(self, username: str) -> User | None:
        """
        Find a user by username.

        Args:
            username: The username to search for.

        Returns:
            The user if found, None otherwise.
        """
        return await self.find_one_by(username=username)

    async def get_by_email(self, email: str) -> User | None:
        """
        Find a user by email.

        Args:
            email: The email address to search for.

        Returns:
            The user if found, None otherwise.
        """
        return await self.find_one_by(email=email)

    async def get_active_users(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[User]:
        """
        Get all active users.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            List of active users.
        """
        return await self.find_many_by(is_active=True, skip=skip, limit=limit)

    async def get_superusers(self) -> Sequence[User]:
        """
        Get all superuser accounts.

        Returns:
            List of superuser accounts.
        """
        return await self.find_many_by(is_superuser=True)

    async def deactivate_user(self, user_id: str) -> User | None:
        """
        Deactivate a user account.

        Args:
            user_id: UUID of the user to deactivate.

        Returns:
            The updated user or None if not found.
        """
        return await self.update(user_id, is_active=False)

    async def activate_user(self, user_id: str) -> User | None:
        """
        Activate a user account.

        Args:
            user_id: UUID of the user to activate.

        Returns:
            The updated user or None if not found.
        """
        return await self.update(user_id, is_active=True)

    async def exists_any(self) -> bool:
        """
        Check if any users exist in the database.

        Returns:
            True if at least one user exists, False otherwise.
        """
        stmt = select(self.model.id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
