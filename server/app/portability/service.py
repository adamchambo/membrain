"""Versioned, additive portable banks; runtime credentials and leases excluded."""

import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, LargeBinary, select, update
from sqlalchemy.exc import IntegrityError, DataError, StatementError

from app.errors import Conflict
from app.jobs.service import enqueue, enqueue_capture, enqueue_embedding
from app.models import Base
from app.portability.models import ImportBatch

FORMAT = "membrain.bank.v2"
V1_FORMATS = ("membrain.bank.v1", "oracle.bank.v1")
TABLES = (
    "conversations", "captures", "ai_proposals", "concepts", "capture_concepts",
    "explanation_revisions", "resources", "concept_resources", "concept_relationships",
    "review_sessions", "review_scope_concepts", "review_questions", "review_attempts", "review_attempt_concepts",
    "subjects", "subject_concepts", "source_versions", "source_chunks", "learning_artifacts", "learning_suggestions",
    "conversation_turns", "learning_needs", "learning_need_events",
)
DEFERRED = {"captures": {"reply_to_proposal_id"}, "subjects": {"parent_id"},
            "learning_suggestions": {"applied_revision_id"}, "conversations": {"subject_id"}}
# Suggestions must exist before revisions bearing their provenance are inserted.
ORDER = ("conversations", "captures", "conversation_turns", "ai_proposals", "concepts", "capture_concepts", "learning_artifacts",
         "learning_suggestions", "explanation_revisions", "resources", "concept_resources", "concept_relationships",
         "review_sessions", "review_scope_concepts", "review_questions", "review_attempts", "review_attempt_concepts",
         "subjects", "subject_concepts", "source_versions", "source_chunks", "learning_needs", "learning_need_events")
# Columns added by v2, filled when importing a v1 document; v1 data predates automatic organisation.
V2_TABLES = ("conversation_turns", "learning_needs", "learning_need_events")
V2_COLUMNS = {
    "conversations": {"subject_id": None, "active_activity": None},
    "subjects": {"aliases": [], "origin": "user"},
    "subject_concepts": {"origin": "user", "capture_id": None},
    "review_sessions": {"conversation_id": None, "target_count": None},
    "review_questions": {"format": "open", "options": None, "answer_key": None},
}


def encode(value):
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode()}
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    return value


def export_bank(db):
    # One repeatable-read transaction gives a coherent provenance snapshot.
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    tables = {}
    total = 0
    for name in TABLES:
        table = Base.metadata.tables[name]
        rows = db.execute(select(table).limit(10001)).mappings().all()
        total += len(rows)
        if total > 10000:
            raise Conflict("Portable JSON is limited to 10000 records; use a database backup for this bank")
        tables[name] = [{key: encode(value) for key, value in row.items()} for row in rows]
    result = {"format": FORMAT, "tables": tables,
              "excluded": ["credentials", "embedding_vectors", "runtime_jobs", "audio", "provider_connections"]}
    if len(json.dumps(result).encode()) > 32 * 1024 * 1024:
        raise Conflict("Portable JSON is limited to 32 MiB; use a database backup for this bank")
    return result


def upgrade_v1(tables: dict) -> dict:
    """Return v1 tables in v2 shape: new tables empty, new columns at their v1-equivalent value.

    Only the known added columns are filled, so a malformed v1 document still fails
    exact-column validation. A membership's creation time is unknown in v1; its subject's
    creation time is used as the earliest truthful bound.
    """
    if not isinstance(tables, dict) or set(tables) != set(TABLES) - set(V2_TABLES):
        raise Conflict("Unsupported portable format or table set")
    subject_times = {item.get("id"): item.get("created_at") for item in tables.get("subjects", []) if isinstance(item, dict)}
    upgraded = {name: [] for name in V2_TABLES}
    for name, items in tables.items():
        if not isinstance(items, list):
            raise Conflict("Portable table must contain at most 10000 records")
        added = V2_COLUMNS.get(name, {})
        upgraded[name] = [{**added, **({"created_at": subject_times.get(item.get("subject_id"))} if name == "subject_concepts" else {}),
                           **item} if isinstance(item, dict) else item for item in items]
    return upgraded


def validate(document):
    if document.get("format") in V1_FORMATS:
        tables = upgrade_v1(document.get("tables"))
    elif document.get("format") == FORMAT and isinstance(document.get("tables"), dict) and set(document["tables"]) == set(TABLES):
        tables = document["tables"]
    else:
        raise Conflict("Unsupported portable format or table set")
    serialized = json.dumps(document, sort_keys=True)
    if len(serialized.encode()) > 32 * 1024 * 1024:
        raise Conflict("Portable JSON exceeds 32 MiB")
    document = {**document, "tables": tables}
    counts, ids, rows = {}, {}, {}
    for name in TABLES:
        table = Base.metadata.tables[name]
        items = document["tables"][name]
        if not isinstance(items, list) or len(items) > 10000:
            raise Conflict("Portable table must contain at most 10000 records")
        counts[name], rows[name] = len(items), []
        for item in items:
            if not isinstance(item, dict) or set(item) != set(table.columns.keys()):
                raise Conflict(f"Portable columns do not match {name}")
            row = {}
            try:
                for column in table.columns:
                    value = item[column.name]
                    if value is None:
                        if not column.nullable:
                            raise ValueError()
                    elif isinstance(column.type, LargeBinary):
                        value = base64.b64decode(value["base64"], validate=True)
                        if len(value) > 2 * 1024 * 1024:
                            raise ValueError()
                    elif isinstance(column.type, DateTime):
                        value = datetime.fromisoformat(value)
                        if value.tzinfo is None:
                            raise ValueError()
                    elif column.type.python_type is UUID:
                        value = UUID(value)
                    elif column.type.python_type is str:
                        if not isinstance(value, str) or (getattr(column.type, "length", None) and len(value) > column.type.length):
                            raise ValueError()
                    elif column.type.python_type is int:
                        if not isinstance(value, int) or isinstance(value, bool):
                            raise ValueError()
                    elif column.type.python_type is dict:
                        # JSONB holds objects (payloads, effects) and arrays (aliases, progress, options).
                        if not isinstance(value, (dict, list)):
                            raise ValueError()
                    row[column.name] = value
                key = tuple(row[c.name] for c in table.primary_key)
                if key in ids.setdefault(name, set()):
                    raise ValueError()
                ids[name].add(key)
            except (ValueError, TypeError, KeyError) as exc:
                raise Conflict(f"Invalid portable record in {name}") from exc
            rows[name].append(row)
    if sum(counts.values()) > 10000:
        raise Conflict("Portable bank exceeds 10000 records")
    for name, items in rows.items():
        for row in items:
            for fk in Base.metadata.tables[name].foreign_keys:
                value = row[fk.parent.name]
                if value is not None and (value,) not in ids.get(fk.column.table.name, set()):
                    raise Conflict(f"Missing portable reference in {name}.{fk.parent.name}")
    return rows, counts, hashlib.sha256(serialized.encode()).hexdigest()


def remap_json(value, mapping, field=None):
    if field in {"raw_text", "body", "explanation", "explanation_text", "source_excerpts", "quote", "text", "content", "prompt", "response", "rationale", "title", "note", "uri", "source_uri", "question", "decision_note"}:
        return value
    if isinstance(value, str):
        return str(mapping[value]) if value in mapping else value
    if isinstance(value, list):
        return [remap_json(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: remap_json(item, mapping, key) for key, item in value.items()}
    return value


def import_bank(db, document, request_id, preview=True):
    rows, counts, digest = validate(document)
    if preview:
        return {"valid": True, "counts": counts, "policy": "copy_with_new_ids", "writes": False}
    try:
        with db.begin():
            previous = db.get(ImportBatch, request_id)
            if previous:
                if previous.content_hash != digest:
                    raise Conflict("This import request_id was already used for different content")
                return previous.report
            mapping = {str(value): uuid4() for items in rows.values() for row in items for value in row.values() if isinstance(value, UUID)}
            postponed = []
            for name in ORDER:
                table = Base.metadata.tables[name]
                for source in rows[name]:
                    row = {}
                    for key, value in source.items():
                        if isinstance(value, UUID):
                            value = mapping[str(value)]
                        elif isinstance(value, (dict, list)):
                            value = remap_json(value, mapping)
                        # Legacy review scopes/feedback are JSON strings, not JSONB.
                        elif isinstance(value, str) and key in ("requested_scope", "feedback"):
                            try:
                                value = json.dumps(remap_json(json.loads(value), mapping))
                            except ValueError:
                                pass
                        row[key] = value
                    deferred = {key: row[key] for key in DEFERRED.get(name, ()) if row[key] is not None}
                    for key in deferred:
                        row[key] = None
                    db.execute(table.insert().values(**row))
                    if deferred:
                        postponed.append((table, row["id"], deferred))
            for table, item_id, values in postponed:
                db.execute(update(table).where(table.c.id == item_id).values(**values))
            # Work is rebuilt under the destination configuration, never imported.
            # A conversation turn owns its capture; processing it as a plain capture too would bank it twice.
            turn_captures = {row["capture_id"] for row in rows["conversation_turns"]}
            for row in rows["captures"]:
                if row["status"] == "pending" and row["id"] not in turn_captures:
                    enqueue_capture(db, mapping[str(row["id"])])
            for row in sorted(rows["conversation_turns"], key=lambda item: item["sequence"]):
                if row["completed_at"] is None:
                    item_id = mapping[str(row["id"])]
                    enqueue(db, dedup_key=f"turn:{item_id}", kind="turn", arguments={"turn_id": str(item_id)})
            for row in rows["explanation_revisions"]:
                if row["retracted_at"] is None:
                    enqueue_embedding(db, mapping[str(row["id"])])
            for row in rows["source_versions"]:
                if row["extracted_text"] is None and row["source_bytes"]:
                    item_id = mapping[str(row["id"])]
                    enqueue(db, dedup_key=f"source:{item_id}", kind="resource_extract", arguments={"version_id": str(item_id)})
            for row in rows["learning_artifacts"]:
                if row["output"] is None:
                    item_id = mapping[str(row["id"])]
                    enqueue(db, dedup_key=f"learning:{item_id}", kind="learning", arguments={"artifact_id": str(item_id)})
            for row in rows["review_attempts"]:
                if row["feedback"] is None and row["question_id"] is not None:
                    item_id = mapping[str(row["id"])]
                    enqueue(db, dedup_key=f"review-feedback:{item_id}", kind="review_feedback", attempt_id=item_id)
            report = {"valid": True, "counts": counts, "policy": "copy_with_new_ids", "writes": True,
                      "id_map": {key: str(value) for key, value in mapping.items()}}
            db.add(ImportBatch(request_id=request_id, content_hash=digest, report=report))
            db.flush()
            return report
    except (IntegrityError, DataError, StatementError) as exc:
        raise Conflict("Import violates a bank constraint; no records were imported") from exc
