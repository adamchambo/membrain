"""Stable embedding profiles and validated compatible-endpoint vectors."""

import hashlib
import json
import math
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.providers.compatible import post_json
from app.errors import NotConfigured, Unavailable
from app.jobs.models import EmbeddingProfile


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
    if not os.getenv("ORACLE_EMBEDDINGS_URL") or not os.getenv("ORACLE_EMBEDDING_REVISION"):
        raise NotConfigured("An embedding endpoint and pinned model/deployment revision are required")
    try:
        return Profile(model=os.getenv("ORACLE_EMBEDDING_MODEL", "nomic-embed-text-v1.5"),
                       revision=os.environ["ORACLE_EMBEDDING_REVISION"],
                       dimensions=int(os.getenv("ORACLE_EMBEDDING_DIMENSIONS", "768")),
                       document_prefix=os.getenv("ORACLE_EMBEDDING_DOCUMENT_PREFIX", "search_document: "),
                       query_prefix=os.getenv("ORACLE_EMBEDDING_QUERY_PREFIX", "search_query: "))
    except ValueError as exc:
        raise NotConfigured("Embedding profile settings are invalid") from exc


def persist_profile(db: Session, profile: Profile) -> None:
    db.execute(insert(EmbeddingProfile).values(key=profile.key, settings=profile.model_dump())
               .on_conflict_do_nothing(index_elements=[EmbeddingProfile.key]))


def embed(text: str, profile: Profile, *, query: bool = False) -> list[float]:
    """Embed text with profile's query/document prefix and validate its dimension."""
    if configured_profile().key != profile.key:
        raise NotConfigured("This job's embedding profile is not served by the current configuration")
    result = post_json(os.environ["ORACLE_EMBEDDINGS_URL"], {
        "model": profile.model,
        "input": (profile.query_prefix if query else profile.document_prefix) + text,
    }, os.getenv("ORACLE_EMBEDDING_API_KEY"))
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
