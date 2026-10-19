"""Stable embedding profiles and validated compatible-endpoint vectors."""

import hashlib
import json
import math
import os
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.providers.compatible import post_json
from app.errors import NotConfigured, Unavailable
from app.jobs.models import EmbeddingProfile
from app.config import read_config, setting


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str
    revision: str
    dimensions: int = Field(default=768, ge=1, le=16000)
    document_prefix: str = "search_document: "
    query_prefix: str = "search_query: "
    normalization: Literal["l2"] = "l2"

    @field_validator("model", "revision")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A model and revision identity are required")
        return value.strip()

    @property
    def key(self) -> str:
        content = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return "embedding:" + hashlib.sha256(content.encode()).hexdigest()


def configured_profile() -> Profile:
    if not setting("ORACLE_EMBEDDINGS_URL") or not setting("ORACLE_EMBEDDING_REVISION"):
        raise NotConfigured("An embedding endpoint and pinned model/deployment revision are required")
    try:
        return Profile(model=setting("ORACLE_EMBEDDING_MODEL", "nomic-embed-text-v1.5"),
                       revision=setting("ORACLE_EMBEDDING_REVISION"),
                       dimensions=int(setting("ORACLE_EMBEDDING_DIMENSIONS", "768")),
                       document_prefix=setting("ORACLE_EMBEDDING_DOCUMENT_PREFIX", "search_document: ", allow_empty=True),
                       query_prefix=setting("ORACLE_EMBEDDING_QUERY_PREFIX", "search_query: ", allow_empty=True))
    except ValueError as exc:
        raise NotConfigured("Embedding profile settings are invalid") from exc


def persist_profile(db: Session, profile: Profile) -> None:
    db.execute(insert(EmbeddingProfile).values(key=profile.key, settings=profile.model_dump())
               .on_conflict_do_nothing(index_elements=[EmbeddingProfile.key]))


class EmbeddingClient(Protocol):
    def embed(self, text: str, profile: Profile, *, query: bool = False) -> list[float]:
        """Encode text with profile settings; query selects the query task prefix."""


class CompatibleEmbeddingClient:
    def __init__(self, url: str, api_key: str | None = None):
        self.url, self.api_key = url, api_key

    def embed(self, text: str, profile: Profile, *, query: bool = False) -> list[float]:
        result = post_json(self.url, {
        "model": profile.model,
        "input": (profile.query_prefix if query else profile.document_prefix) + text,
        }, self.api_key)
        return validate_vector(result, profile)


def validate_vector(result: dict, profile: Profile) -> list[float]:
    try:
        values = result["data"][0]["embedding"]
        if not isinstance(values, list) or len(values) != profile.dimensions:
            raise ValueError("Wrong dimension")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values):
            raise ValueError("Non-numeric vector")
        vector = [float(x) for x in values]
        if not all(math.isfinite(x) for x in vector):
            raise ValueError("Non-finite vector")
        length = math.sqrt(sum(x * x for x in vector))
        if not length or not math.isfinite(length):
            raise ValueError("Invalid vector length")
        return [x / length for x in vector]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Unavailable("The embedding endpoint returned an invalid vector") from exc


def get_embedding_client(profile: Profile) -> EmbeddingClient:
    try:
        if configured_profile().key == profile.key:
            return CompatibleEmbeddingClient(setting("ORACLE_EMBEDDINGS_URL"), setting("ORACLE_EMBEDDING_API_KEY"))
    except NotConfigured:
        pass
    connection = read_config().get("embedding_connections", {}).get(profile.key)
    if not connection:
        raise NotConfigured("No endpoint is configured for this embedding profile")
    return CompatibleEmbeddingClient(connection["url"], connection.get("api_key"))


def embed(text: str, profile: Profile, *, query: bool = False) -> list[float]:
    return get_embedding_client(profile).embed(text, profile, query=query)
