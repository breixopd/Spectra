"""Common/shared schemas used across multiple domain modules."""

from typing import Any

from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    """Generic paginated list response."""

    items: list[Any]
    total: int
    page: int
    per_page: int
    pages: int = 0

    def __init__(self, **data: Any) -> None:
        if "pages" not in data and data.get("per_page"):
            data["pages"] = max(1, -(-data["total"] // data["per_page"]))  # ceil division
        super().__init__(**data)


class StatusResponse(BaseModel):
    """Generic status/message response for simple action endpoints."""

    status: str | None = None
    message: str | None = None
