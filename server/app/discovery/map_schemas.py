"""Map placement, confirmed relationships, and semantic leads stay distinct."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class MapPosition(BaseModel):
    x: float
    y: float
    z: float | None = None


class MapNode(BaseModel):
    id: UUID
    label: str
    position: MapPosition | None = None
    excerpt: str | None = None


class ConfirmedMapEdge(BaseModel):
    id: UUID
    source: UUID
    target: UUID
    type: str
    evidence: Literal["user_confirmed"]
    rationale: str | None


class SimilarityCandidate(BaseModel):
    source: UUID
    target: UUID
    score: float
    profile_key: str
    type: Literal["semantic_candidate"]


class ProposedMapEdge(BaseModel):
    suggestion_id: UUID
    source: UUID
    target: UUID
    type: str
    rationale: str


class MapLayout(BaseModel):
    method: Literal["none", "circle", "embedding"]
    version: int
    meaning: str


class ConceptMapRead(BaseModel):
    nodes: list[MapNode]
    confirmed_edges: list[ConfirmedMapEdge]
    similarity_candidates: list[SimilarityCandidate]
    proposed_edges: list[ProposedMapEdge]
    proposals_truncated: bool
    vector_status: Literal["not_requested", "ready", "vectors_pending", "unconfigured"]
    layout: MapLayout
