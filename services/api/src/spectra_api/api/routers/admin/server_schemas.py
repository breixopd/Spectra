"""Schemas for admin server and scaling endpoints."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class ServerConnectionRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(22, ge=1, le=65535)
    username: str = Field("root", min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    password: str | None = None
    private_key: str | None = None
    ssh_known_host: str | None = None


class ProvisionRequest(ServerConnectionRequest):
    service_type: str
    service_port: int = Field(8080, ge=1, le=65535)
    extra_env: dict[str, str] = Field(default_factory=dict, max_length=16)

    @field_validator("extra_env")
    @classmethod
    def validate_extra_env(cls, value: dict[str, str]) -> dict[str, str]:
        for key, env_value in value.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid environment variable name: {key}")
            if len(env_value) > 4096:
                raise ValueError(f"Environment variable '{key}' exceeds 4096 characters")
        return value


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
