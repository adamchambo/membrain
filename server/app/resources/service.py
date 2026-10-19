"""Uploaded source content stays separate from the user's understanding."""

import base64
import binascii
import hashlib
import re
from html.parser import HTMLParser
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import select

from app.errors import Conflict, NotFound
from app.jobs.service import enqueue
from app.knowledge.models import Resource
from app.resources.models import SourceChunk, SourceVersion

MAX_BYTES = 2 * 1024 * 1024


class SourceUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["text/plain", "text/markdown", "text/html"]
    content_base64: str = Field(min_length=1, max_length=2796204)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag in ("p", "div", "br", "h1", "h2", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def decode_upload(data: SourceUpload) -> bytes:
    try:
        content = base64.b64decode(data.content_base64, validate=True)
        if not content or len(content) > MAX_BYTES:
            raise ValueError()
        content.decode("utf-8")
        return content
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise Conflict("Upload must be nonempty UTF-8 text up to 2 MiB") from exc


def upload(db, resource_id: UUID, data: SourceUpload):
    content = decode_upload(data)
    digest = hashlib.sha256(data.media_type.encode() + b"\0" + content).hexdigest()
    with db.begin():
        resource = db.scalar(select(Resource).where(Resource.id == resource_id).with_for_update())
        if not resource:
            raise NotFound("Resource not found")
        if resource.archived_at:
            raise Conflict("Restore this resource before importing content")
        version = db.scalar(select(SourceVersion).where(SourceVersion.resource_id == resource_id, SourceVersion.content_hash == digest))
        if version is None:
            version = SourceVersion(resource_id=resource_id, content_hash=digest, media_type=data.media_type,
                                    source_bytes=content, source_uri=resource.uri)
            db.add(version)
            db.flush()
        job = enqueue(db, dedup_key=f"source:{version.id}", kind="resource_extract", arguments={"version_id": str(version.id)})
        return {"version_id": version.id, "job_id": job}


def prepare(db, arguments):
    version = db.get(SourceVersion, UUID(arguments["version_id"]))
    if not version:
        raise NotFound("Source version not found")
    return {"version_id": version.id, "text": version.source_bytes.decode("utf-8"), "media_type": version.media_type}


def extract(prepared):
    text = prepared["text"]
    if prepared["media_type"] == "text/html":
        parser = TextExtractor()
        parser.feed(text)
        text = "".join(parser.parts)
    return re.sub(r"[ \t]+", " ", text).strip()


def apply(db, prepared, output):
    version = db.scalar(select(SourceVersion).where(SourceVersion.id == prepared["version_id"]).with_for_update())
    if version.extracted_text is None:
        version.extracted_text = output
        for ordinal, start in enumerate(range(0, len(output), 1200)):
            end = min(start + 1200, len(output))
            db.add(SourceChunk(version_id=version.id, ordinal=ordinal, start=start, end=end, text=output[start:end]))
    return {"version_id": str(version.id), "characters": len(output)}


def chunks(db, resource_id: UUID, query: str | None = None, limit=25):
    if not db.get(Resource, resource_id):
        raise NotFound("Resource not found")
    latest = db.scalar(select(SourceVersion).where(SourceVersion.resource_id == resource_id,
        SourceVersion.extracted_text.is_not(None)).order_by(SourceVersion.created_at.desc(), SourceVersion.id.desc()).limit(1))
    if latest is None:
        return {"version_id": None, "items": [], "status": "no_extracted_content"}
    statement = select(SourceChunk).where(SourceChunk.version_id == latest.id)
    if query:
        statement = statement.where(SourceChunk.text.icontains(query, autoescape=True))
    rows = db.scalars(statement.order_by(SourceChunk.ordinal).limit(limit)).all()
    return {"version_id": latest.id, "status": "ready", "items": [
        {"id": row.id, "ordinal": row.ordinal, "start": row.start, "end": row.end, "text": row.text,
         "resource_id": resource_id, "source_uri": latest.source_uri} for row in rows]}
