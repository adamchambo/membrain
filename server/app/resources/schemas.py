from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SourceReceipt(BaseModel):
    version_id: UUID
    job_id: UUID


class ChunkRead(BaseModel):
    id: UUID
    ordinal: int
    start: int
    end: int
    text: str
    resource_id: UUID
    source_uri: str


class ChunkPage(BaseModel):
    version_id: UUID | None
    status: Literal["ready", "no_extracted_content"]
    items: list[ChunkRead]
