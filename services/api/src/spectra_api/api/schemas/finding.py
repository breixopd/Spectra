"""Finding schemas."""

from pydantic import BaseModel, ConfigDict


class FindingResponse(BaseModel):
    """Schema for finding response."""

    id: str
    title: str
    description: str | None
    severity: str
    status: str
    tool_source: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)
