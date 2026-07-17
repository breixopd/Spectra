"""
Base Repository with generic CRUD operations.

Implements the Repository Pattern for clean data access abstraction.
All entity-specific repositories should inherit from this.
"""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_persistence.orm.base import Base

# Generic type for SQLAlchemy models
ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic async repository implementing CRUD operations.

    Usage:
        class TargetRepository(BaseRepository[Target]):
            def __init__(self, session: AsyncSession):
                super().__init__(Target, session)

            async def find_by_value(self, value: str) -> Target | None:
                return await self.find_one_by(value=value)
    """

    def __init__(self, model: type[ModelType], session: AsyncSession):
        """
        Initialize repository with model class and database session.

        Args:
            model: The SQLAlchemy model class.
            session: Async database session.
        """
        self.model = model
        self.session = session
        # Cache allowed filter fields based on model columns
        self._allowed_filters = {c.key for c in inspect(model).mapper.column_attrs}

    def _validate_filters(self, kwargs: dict) -> None:
        """Validate that filter keys are valid model columns."""
        for key in kwargs:
            if key not in self._allowed_filters:
                raise ValueError(f"Invalid filter field: {key}")

    async def create(self, **kwargs: Any) -> ModelType:
        """
        Create a new entity.

        Args:
            **kwargs: Model field values.

        Returns:
            The created entity.
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(
        self,
        entity_id: str | UUID,
        *,
        options: Sequence[Any] | None = None,
    ) -> ModelType | None:
        """
        Get entity by ID.

        Args:
            entity_id: UUID of the entity.
            options: Optional SQLAlchemy loader options (e.g. selectinload).

        Returns:
            The entity or None if not found.
        """
        stmt = select(self.model).where(self.model.id == str(entity_id))
        if options:
            stmt = stmt.options(*options)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        options: Sequence[Any] | None = None,
    ) -> Sequence[ModelType]:
        """
        Get all entities with pagination.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            options: Optional SQLAlchemy loader options (e.g. selectinload).

        Returns:
            List of entities.
        """
        stmt = select(self.model).offset(skip).limit(limit)
        if options:
            stmt = stmt.options(*options)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def find_one_by(self, **kwargs) -> ModelType | None:
        """
        Find a single entity by field values.

        Args:
            **kwargs: Field-value pairs to match.

        Returns:
            The entity or None.
        """
        self._validate_filters(kwargs)
        stmt = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_many_by(
        self,
        skip: int = 0,
        limit: int = 100,
        options: Sequence[Any] | None = None,
        **kwargs: Any,
    ) -> Sequence[ModelType]:
        """
        Find multiple entities by field values.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            options: Optional SQLAlchemy loader options (e.g. selectinload).
            **kwargs: Field-value pairs to match.

        Returns:
            List of matching entities.
        """
        self._validate_filters(kwargs)
        stmt = select(self.model).filter_by(**kwargs).offset(skip).limit(limit)
        if options:
            stmt = stmt.options(*options)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update(
        self,
        entity_id: str | UUID,
        **kwargs: Any,
    ) -> ModelType | None:
        """
        Update an entity by ID.

        Args:
            entity_id: UUID of the entity.
            **kwargs: Fields to update.

        Returns:
            The updated entity or None.
        """
        stmt = update(self.model).where(self.model.id == str(entity_id)).values(**kwargs).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()

    async def delete(self, entity_id: str | UUID) -> bool:
        """
        Delete an entity by ID.

        Args:
            entity_id: UUID of the entity.

        Returns:
            True if deleted, False if not found.
        """
        stmt = delete(self.model).where(self.model.id == str(entity_id))
        result = await self.session.execute(stmt)
        return result.rowcount > 0 if result.rowcount else False  # type: ignore[union-attr]

    async def count(self, **kwargs) -> int:
        """
        Count entities matching criteria.

        Args:
            **kwargs: Optional filter criteria.

        Returns:
            Number of matching entities.
        """
        self._validate_filters(kwargs)
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model)  # pylint: disable=not-callable
        if kwargs:
            stmt = stmt.filter_by(**kwargs)
        result = await self.session.execute(stmt)
        return result.scalar_one()
