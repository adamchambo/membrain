"""Setup is explicit server administration, independent of normal capture."""

from typing import Literal
from urllib.parse import urlsplit
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.ai.embeddings import Profile


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    model: str = Field(min_length=1, max_length=255)
    api_key: SecretStr | None = None

    @field_validator("url")
    @classmethod
    def valid_endpoint(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an HTTP(S) endpoint without embedded credentials or query parameters")
        return value


class ChatEndpoint(Endpoint):
    profile: Literal["standard", "qwen3_fast"] = "standard"
    max_tokens: int = Field(default=2048, ge=64, le=8192)
    temperature: float = Field(default=0.2, ge=0, le=2)


class EmbeddingEndpoint(Endpoint):
    profile: Profile


class SetupConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_url: SecretStr | None = None
    database_mode: Literal["bundled", "existing"] = "existing"
    chat: ChatEndpoint | None = None
    embeddings: EmbeddingEndpoint | None = None


class CapabilityCheck(BaseModel):
    capabilities: list[Literal["database", "chat", "embeddings"]] = Field(default_factory=lambda: ["database", "chat", "embeddings"])


class MigrationRequest(EmbeddingEndpoint):
    pass


class CapabilitySettings(BaseModel):
    configured: bool
    model: str | None


class SettingsRead(BaseModel):
    database_configured: bool
    chat: CapabilitySettings
    embeddings: CapabilitySettings
    environment_overrides: list[str] = Field(default_factory=list)


class ProbeRead(BaseModel):
    ready: bool
    detail: str | None = None
    migration: str | None = None
    profile_key: str | None = None
    dimensions: int | None = None


class WorkerRead(BaseModel):
    ready: bool
    last_seen_at: datetime | None = None


class ReadinessRead(BaseModel):
    settings: SettingsRead
    database: ProbeRead
    worker: WorkerRead
    pending_work: dict[str, int]


class MigrationRead(BaseModel):
    id: UUID
    status: Literal["running", "completed", "cancelled"]
    target_profile_key: str
    source_profile_key: str | None
    missing_explanations: int
