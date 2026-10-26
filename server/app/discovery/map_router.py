"""Text-accessible map data; similarity never implies a prerequisite."""

import math
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.discovery.layout import embedding_positions
from app.errors import Conflict, NotConfigured
from app.knowledge.models import Concept, ConceptEmbedding, ConceptRelationship
from app.knowledge.service import latest_revision
from app.learning.scopes import resolve_subject
from app.learning.models import LearningSuggestion
from app.setup.profiles import active_profile
from app.discovery.map_schemas import ConceptMapRead

router = APIRouter(prefix="/api/v1", tags=["concept map"])
Db = Annotated[Session, Depends(get_db)]
EXCERPT = 240
LAYOUT_MEANING = {
    "none": "No coordinates; nodes are an unordered list.",
    "circle": "Display placement only; distance is not evidence of prerequisites",
    "embedding": "PCA of latest explanation vectors; nearby points have similar saved wording. Distance is not a prerequisite.",
}


class MapRequest(BaseModel):
    concept_ids: list[UUID] = Field(default_factory=list, max_length=100)
    subject_id: UUID | None = None
    layout: Literal["none", "circle", "embedding"] = "none"
    include_similarity: bool = True
    minimum_similarity: float = Field(default=0.7, ge=-1, le=1)


@router.post("/concept-map", response_model=ConceptMapRead, response_model_exclude_unset=True)
def concept_map(data: MapRequest, db: Db):
    if bool(data.concept_ids) == bool(data.subject_id):
        raise Conflict("Choose concept_ids or subject_id")
    ids = resolve_subject(db, data.subject_id) if data.subject_id else data.concept_ids
    if len(ids) > 100:
        raise Conflict("Choose a map scope with at most 100 concepts")
    concepts = db.scalars(select(Concept).where(Concept.id.in_(ids), Concept.archived_at.is_(None)).order_by(Concept.id)).all()
    ids = [c.id for c in concepts]
    edges = [{"id": r.id, "source": r.source_concept_id, "target": r.target_concept_id,
              "type": r.relation_type, "evidence": "user_confirmed", "rationale": r.rationale}
        for r in db.scalars(select(ConceptRelationship).where(ConceptRelationship.archived_at.is_(None), ConceptRelationship.source_concept_id.in_(ids),
            ConceptRelationship.target_concept_id.in_(ids))).all()]
    need_vectors = data.include_similarity or data.layout == "embedding"
    candidates, placed, status = [], {}, "not_requested"
    if need_vectors:
        try:
            profile = active_profile(db)
            vectors = []
            for concept in concepts:
                revision = latest_revision(db, concept.id)
                vector = db.scalar(select(ConceptEmbedding).where(ConceptEmbedding.explanation_revision_id == revision.id,
                    ConceptEmbedding.model_key == profile.key)) if revision else None
                if vector is not None:
                    vectors.append((concept.id, list(vector.embedding)))
            if data.include_similarity:
                for index, (source, a) in enumerate(vectors):
                    for target, b in vectors[index + 1:]:
                        if len(a) != profile.dimensions or len(b) != profile.dimensions:
                            continue
                        denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
                        score = sum(x*y for x,y in zip(a,b)) / denominator if denominator else -1
                        if score >= data.minimum_similarity:
                            candidates.append({"source": source, "target": target, "score": score,
                                               "profile_key": profile.key, "type": "semantic_candidate"})
            if data.layout == "embedding":
                for (concept_id, _), position in zip(vectors, embedding_positions([row[1] for row in vectors])):
                    placed[concept_id] = position
            status = "ready" if len(vectors) == len(concepts) else "vectors_pending"
        except NotConfigured:
            status = "unconfigured"
    nodes = []
    for index, concept in enumerate(concepts):
        revision = latest_revision(db, concept.id)
        body = revision.body if revision else ""
        excerpt = (body if len(body) <= EXCERPT else body[:EXCERPT] + " …") or None
        node = {"id": concept.id, "label": concept.title, "excerpt": excerpt}
        if data.layout == "circle":
            angle = 2 * math.pi * index / max(1, len(concepts))
            node["position"] = {"x": math.cos(angle), "y": math.sin(angle)}
        elif concept.id in placed:
            node["position"] = placed[concept.id]
        nodes.append(node)
    proposals = db.scalars(select(LearningSuggestion).where(LearningSuggestion.kind == "relationship",
        LearningSuggestion.status == "pending", LearningSuggestion.payload["concept_id"].astext.in_([str(x) for x in ids]),
        LearningSuggestion.payload["target_concept_id"].astext.in_([str(x) for x in ids]))
        .order_by(LearningSuggestion.created_at.desc()).limit(501)).all()
    return {"nodes": nodes, "confirmed_edges": edges, "similarity_candidates": candidates,
            "proposed_edges": [{"suggestion_id": p.id, "source": p.payload["concept_id"], "target": p.payload["target_concept_id"],
                                "type": p.payload["relation_type"], "rationale": p.payload["rationale"]} for p in proposals[:500]],
            "proposals_truncated": len(proposals) > 500,
            "vector_status": status,
            "layout": {"method": data.layout, "version": 1, "meaning": LAYOUT_MEANING[data.layout]}}
