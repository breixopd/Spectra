"""Schemas for admin server and scaling endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServerConnectionRequest(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    private_key: str | None = None
    ssh_known_host: str | None = None


class ProvisionRequest(ServerConnectionRequest):
    service_type: str
    service_port: int = 8080
    extra_env: dict[str, str] = Field(default_factory=dict)


class DeprovisionRequest(ServerConnectionRequest):
    service_type: str = "sandbox_worker"


class UpdateServerNodeRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    is_active: bool | None = None
    is_primary: bool | None = None
    weight: int | None = Field(None, ge=1, le=100)
    max_capacity: int | None = Field(None, ge=1, le=1000)
    service_type: str | None = Field(
        None,
        pattern=r"^(sandbox_worker|app_worker|tools_worker|db_replica|db_backup|storage)$",
    )
