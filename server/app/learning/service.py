"""Durable learning tasks with validated evidence and explicit adoption."""

import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select

from app.ai.client import get_chat_client
from app.errors import Conflict, NotFound, Unavailable
from app.jobs.service import enqueue, enqueue_embedding
from app.knowledge.models import Concept, ConceptRelationship, ExplanationRevision, Resource
from app.knowledge.service import latest_revision
from app.learning.models import LearningArtifact, LearningSuggestion
from app.learning.prompts import SYSTEM, VERSION
from app.learning.schemas import LearningOutput
from app.resources.service import chunks
from app.review.models import ReviewAttempt, ReviewAttemptConcept


def create(db, data):
    with db.begin():
        for concept_id in data.concept_ids:
            concept = db.scalar(select(Concept).where(Concept.id == concept_id).with_for_update())
            if not concept or concept.archived_at:
                raise NotFound("Active concept not found")
        for resource_id in data.resource_ids:
            resource = db.scalar(select(Resource).where(Resource.id == resource_id).with_for_update())
            if not resource or resource.archived_at:
                raise NotFound("Active resource not found")
        inputs = data.model_dump(mode="json")
        if data.parent_artifact_id:
            parent = db.get(LearningArtifact, data.parent_artifact_id)
            if not parent:
                raise NotFound("Previous learning result not found")
            if parent.output is None:
                raise Conflict("The previous explanation is still processing. Wait for its result, then retry your follow-up.")
            history = parent.inputs.get("history", []) + [
                {"role": "user", "content": parent.inputs.get("question", "")[:4000]},
                {"role": "assistant", "content": parent.output.get("content", "")[:4000]}]
            recent = []
            remaining = 12000
            for turn in reversed(history[-6:]):
                if not remaining:
                    break
                content = turn["content"][-remaining:]
                recent.append({"role": turn["role"], "content": content})
                remaining -= len(content)
            inputs["history"] = list(reversed(recent))
        item = LearningArtifact(kind=data.kind, inputs=inputs)
        db.add(item)
        db.flush()
        job_id = enqueue(db, dedup_key=f"learning:{item.id}", kind="learning", arguments={"artifact_id": str(item.id)})
        return {"artifact_id": item.id, "job_id": job_id}


def prepare(db, arguments):
    item = db.get(LearningArtifact, UUID(arguments["artifact_id"]))
    if not item:
        raise NotFound("Learning artifact not found")
    context = {"concepts": [], "source_chunks": [], "review_evidence": [], "dialogue": item.inputs.get("history", [])}
    for raw_id in item.inputs["concept_ids"]:
        concept_id = UUID(raw_id)
        concept = db.get(Concept, concept_id)
        if not concept or concept.archived_at:
            raise Conflict("Learning scope contains an archived concept")
        revision = latest_revision(db, concept_id)
        history = db.scalars(select(ExplanationRevision).where(ExplanationRevision.concept_id == concept_id)
            .order_by(ExplanationRevision.revision_number.desc()).limit(5)).all()
        context["concepts"].append({"id": str(concept.id), "title": concept.title,
            "revision_id": str(revision.id) if revision else None, "explanation": revision.body if revision else None,
            "history": [{"id": str(r.id), "body": r.body, "retracted": bool(r.retracted_at)} for r in history]})
    for resource_id in item.inputs["resource_ids"]:
        resource = db.get(Resource, UUID(resource_id))
        if resource and not resource.archived_at:
            context["source_chunks"].extend(chunks(db, UUID(resource_id), limit=10)["items"])
    attempts = db.scalars(select(ReviewAttempt).join(ReviewAttemptConcept, ReviewAttemptConcept.review_attempt_id == ReviewAttempt.id)
        .where(ReviewAttemptConcept.concept_id.in_([UUID(x) for x in item.inputs["concept_ids"]]))
        .order_by(ReviewAttempt.answered_at.desc()).distinct().limit(10)).all()
    context["review_evidence"] = [{"id": str(a.id), "prompt": a.prompt, "response": a.response, "feedback": a.feedback} for a in attempts]
    return {"artifact_id": item.id, "request": item.inputs, "context": context}


def generate(prepared):
    client = get_chat_client()
    payload = json.dumps({"request": prepared["request"], "context": prepared["context"],
                          "output_schema": LearningOutput.model_json_schema()}, default=str)
    omitted = 0
    try:
        document = json.loads(client.generate(SYSTEM, payload))
        # An unscoped teaching request has no authority to propose changes to saved
        # concepts. Retain valid teaching content while discarding this optional
        # channel before validating IDs; scoped requests remain strictly validated.
        if not prepared["context"]["concepts"] and isinstance(document, dict):
            suggestions = document.get("suggestions", [])
            if isinstance(suggestions, list) and suggestions:
                omitted = len(suggestions)
                document["suggestions"] = []
                if isinstance(document.get("uncertainty", []), list):
                    document["uncertainty"] = document.get("uncertainty", []) + [
                        "No saved concepts were selected; concept-change suggestions were not retained."]
        result = LearningOutput.model_validate(document)
    except (ValidationError, ValueError) as exc:
        raise Unavailable("The model returned an invalid learning result") from exc
    validate_evidence(result, prepared)
    return {"result": result.model_dump(mode="json"), "model_key": client.model_key, "omitted_suggestions": omitted}


def validate_evidence(output, prepared):
    sources = {str(c["id"]): c["text"] for c in prepared["context"]["source_chunks"]}
    concepts = {c["id"] for c in prepared["context"]["concepts"]}
    citations = list(output.citations)
    for suggestion in output.suggestions:
        if str(suggestion.concept_id) not in concepts or (suggestion.target_concept_id and str(suggestion.target_concept_id) not in concepts):
            raise Unavailable("A suggestion referenced an unavailable concept")
        if suggestion.concept_id == suggestion.target_concept_id:
            raise Unavailable("A relationship cannot point to itself")
        citations.extend(suggestion.citations)
    for citation in citations:
        if citation.quote not in sources.get(str(citation.chunk_id), ""):
            raise Unavailable("A generated citation does not match supplied source content")
    if output.verification == "sources_compared" and not output.citations:
        raise Unavailable("A source comparison requires matching citations")


def apply(db, prepared, output):
    item = db.scalar(select(LearningArtifact).where(LearningArtifact.id == prepared["artifact_id"]).with_for_update())
    if item.output is None:
        # Retain the exact input context used for inference, including revision IDs.
        item.inputs = {**item.inputs, "context": json.loads(json.dumps(prepared["context"], default=str)),
                       "omitted_suggestions": output.get("omitted_suggestions", 0)}
        item.output, item.model_key, item.prompt_version = output["result"], output["model_key"], VERSION
        for payload in output["result"]["suggestions"]:
            db.add(LearningSuggestion(artifact_id=item.id, kind=payload["kind"], payload=payload))
    return {"artifact_id": str(item.id)}


def detail(db, artifact_id):
    item = db.get(LearningArtifact, artifact_id)
    if not item:
        raise NotFound("Learning artifact not found")
    suggestions = db.scalars(select(LearningSuggestion).where(LearningSuggestion.artifact_id == artifact_id)).all()
    return {"id": item.id, "kind": item.kind, "inputs": item.inputs, "output": item.output,
            "model_key": item.model_key, "prompt_version": item.prompt_version,
            "suggestions": [{"id": s.id, "payload": s.payload, "status": s.status,
                "applied_revision_id": s.applied_revision_id, "decision_note": s.decision_note} for s in suggestions]}


def decide(db, suggestion_id, data):
    with db.begin():
        item = db.scalar(select(LearningSuggestion).where(LearningSuggestion.id == suggestion_id).with_for_update())
        if not item:
            raise NotFound("Suggestion not found")
        if item.status != "pending":
            expected = "adopted" if data.action == "adopt" else "dismissed"
            if item.status == expected and item.decision_note == data.message:
                return {"id": item.id, "status": item.status, "revision_id": item.applied_revision_id}
            raise Conflict("Suggestion already has a different decision")
        payload = item.payload
        concept_id = UUID(payload["concept_id"])
        concept = db.scalar(select(Concept).where(Concept.id == concept_id).with_for_update())
        if data.action == "adopt":
            if concept.archived_at:
                raise Conflict("Restore the concept before adopting a suggestion")
            artifact = db.get(LearningArtifact, item.artifact_id)
            reference = next(c for c in artifact.inputs["context"]["concepts"] if c["id"] == str(concept_id))
            current = latest_revision(db, concept_id)
            if reference["revision_id"] != (str(current.id) if current else None):
                raise Conflict("Understanding changed since this suggestion; generate a fresh suggestion")
            if item.kind == "correction":
                number = db.scalar(select(func.max(ExplanationRevision.revision_number)).where(ExplanationRevision.concept_id == concept_id)) or 0
                revision = ExplanationRevision(concept_id=concept_id, revision_number=number + 1,
                    body=payload["explanation_text"], origin="user_confirmed_suggestion", suggestion_id=item.id)
                db.add(revision)
                db.flush()
                item.applied_revision_id = revision.id
                enqueue_embedding(db, revision.id)
            elif item.kind == "relationship":
                target_id = UUID(payload["target_concept_id"])
                target = db.get(Concept, target_id)
                if not target or target.archived_at:
                    raise Conflict("The relationship target is unavailable")
                existing = db.scalar(select(ConceptRelationship).where(ConceptRelationship.source_concept_id == concept_id,
                    ConceptRelationship.target_concept_id == target_id, ConceptRelationship.relation_type == payload["relation_type"]))
                if not existing:
                    db.add(ConceptRelationship(source_concept_id=concept_id, target_concept_id=target_id,
                        relation_type=payload["relation_type"], rationale=payload["rationale"]))
                else:
                    existing.archived_at = None
            # Adopting a possible gap records interest; it does not assert a deficit.
        item.status = "adopted" if data.action == "adopt" else "dismissed"
        item.decision_note, item.decided_at = data.message, datetime.now(timezone.utc)
        return {"id": item.id, "status": item.status, "revision_id": item.applied_revision_id}
