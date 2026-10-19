"""Text and vector retrieval over current, active user explanations."""

from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.ai.embeddings import configured_profile, embed
from app.errors import NotConfigured
from app.knowledge.models import Concept, ConceptEmbedding, ConceptRelationship, ExplanationRevision, Resource
from app.knowledge.service import require_concept
from app.discovery.schemas import RelatedResult, SearchHit, SearchResult
from app.setup.profiles import active_profile


def latest_revisions():
    return select(ExplanationRevision.concept_id, func.max(ExplanationRevision.revision_number).label("number"))\
        .where(ExplanationRevision.retracted_at.is_(None)).group_by(ExplanationRevision.concept_id).subquery()


def text_search(db: Session, q: str, limit: int) -> list[SearchHit]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    latest = latest_revisions()
    rows = db.execute(select(Concept, ExplanationRevision).join(latest, latest.c.concept_id == Concept.id)
        .join(ExplanationRevision, and_(ExplanationRevision.concept_id == Concept.id,
                                       ExplanationRevision.revision_number == latest.c.number))
        .where(Concept.archived_at.is_(None), or_(Concept.title.ilike(pattern, escape="\\"),
               ExplanationRevision.body.ilike(pattern, escape="\\")))
        .order_by(case((Concept.title.ilike(pattern, escape="\\"), 0), else_=2), Concept.title, Concept.id)
        .limit(limit)).all()
    hits = [SearchHit(id=c.id, type="concept", title=c.title, revision_id=r.id,
                     match_reason="title" if q.casefold() in c.title.casefold() else "explanation") for c, r in rows]
    resources = db.scalars(select(Resource).where(Resource.archived_at.is_(None), or_(
        Resource.title.ilike(pattern, escape="\\"), Resource.note.ilike(pattern, escape="\\"), Resource.uri.ilike(pattern, escape="\\")))
        .order_by(case((Resource.title.ilike(pattern, escape="\\"), 1),
                       (Resource.note.ilike(pattern, escape="\\"), 3), else_=4), Resource.title, Resource.id).limit(limit)).all()
    for resource in resources:
        reason = ("resource_title" if resource.title and q.casefold() in resource.title.casefold() else
                  "resource_note" if resource.note and q.casefold() in resource.note.casefold() else "resource_uri")
        hits.append(SearchHit(id=resource.id, type="resource", title=resource.title or resource.uri, match_reason=reason))
    priority = {"title": 0, "resource_title": 1, "explanation": 2, "resource_note": 3, "resource_uri": 4}
    return sorted(hits, key=lambda hit: (priority[hit.match_reason], hit.title.casefold(), str(hit.id)))[:limit]


def vector_search(db: Session, vector: list[float], profile_key: str, limit: int, exclude_id: UUID | None = None):
    latest = latest_revisions()
    distance = ConceptEmbedding.embedding.cosine_distance(vector)
    query = select(Concept, ExplanationRevision.id, distance.label("distance")).join(
        ExplanationRevision, ExplanationRevision.concept_id == Concept.id).join(
        latest, and_(latest.c.concept_id == Concept.id, latest.c.number == ExplanationRevision.revision_number)).join(
        ConceptEmbedding, ConceptEmbedding.explanation_revision_id == ExplanationRevision.id).where(
        Concept.archived_at.is_(None), ConceptEmbedding.model_key == profile_key)
    if exclude_id:
        query = query.where(Concept.id != exclude_id)
    return [SearchHit(id=concept.id, type="concept", title=concept.title, revision_id=revision_id,
                     match_reason="semantic", match_source="semantic", similarity=max(-1, min(1, 1 - float(d))))
            for concept, revision_id, d in db.execute(query.order_by(distance, Concept.id).limit(limit)).all()]


def pending_count(db: Session, profile_key: str) -> int:
    latest = latest_revisions()
    return db.scalar(select(func.count()).select_from(ExplanationRevision).join(Concept,
        Concept.id == ExplanationRevision.concept_id).join(latest, and_(latest.c.concept_id == Concept.id,
        latest.c.number == ExplanationRevision.revision_number)).outerjoin(ConceptEmbedding, and_(
        ConceptEmbedding.explanation_revision_id == ExplanationRevision.id, ConceptEmbedding.model_key == profile_key))
        .where(Concept.archived_at.is_(None), ConceptEmbedding.id.is_(None))) or 0


def search(db: Session, q: str, mode: str, limit: int) -> SearchResult:
    q = q.strip()
    if not q:
        return SearchResult(items=[], mode=mode)
    # Query inference happens before this request starts a DB transaction.
    profile = None
    if mode != "text":
        with db.begin():
            profile = active_profile(db)
    vector = embed(q, profile, query=True) if profile else None
    text = text_search(db, q, limit) if mode != "semantic" else []
    semantic = vector_search(db, vector, profile.key, limit) if profile else []
    if mode == "hybrid":
        scores, merged = {}, {}
        for hits in (text, semantic):
            for rank, hit in enumerate(hits, 1):
                key = (hit.type, hit.id)
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                if key in merged:
                    merged[key].match_source = "hybrid"
                    merged[key].similarity = hit.similarity
                else:
                    merged[key] = hit.model_copy()
        items = [merged[key] for key in sorted(scores, key=lambda key: (-scores[key], str(key)))[:limit]]
    else:
        items = semantic if profile else text
    return SearchResult(items=items, mode=mode, profile_key=profile.key if profile else None,
                        pending_explanations=pending_count(db, profile.key) if profile else 0)


def related(db: Session, concept_id: UUID, limit: int) -> RelatedResult:
    require_concept(db, concept_id)
    rows = db.scalars(select(ConceptRelationship).where(ConceptRelationship.archived_at.is_(None)).where(
        (ConceptRelationship.source_concept_id == concept_id) | (ConceptRelationship.target_concept_id == concept_id)
    ).order_by(ConceptRelationship.confirmed_at.desc()).limit(limit)).all()
    try:
        profile = active_profile(db)
    except NotConfigured:
        return RelatedResult(confirmed=rows)
    latest = latest_revisions()
    source = db.scalar(select(ConceptEmbedding).join(ExplanationRevision,
        ExplanationRevision.id == ConceptEmbedding.explanation_revision_id).join(latest, and_(
        latest.c.concept_id == ExplanationRevision.concept_id, latest.c.number == ExplanationRevision.revision_number))
        .where(ExplanationRevision.concept_id == concept_id, ConceptEmbedding.model_key == profile.key))
    if source is None:
        return RelatedResult(confirmed=rows, profile_key=profile.key, embedding_status="pending")
    return RelatedResult(confirmed=rows, semantic_candidates=vector_search(db, list(source.embedding), profile.key, limit, concept_id),
                         semantic_available=True, embedding_status="ready", profile_key=profile.key)
