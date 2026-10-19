"""Stable keyset pagination for newest-first UUID records."""

import base64
import binascii
import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_


def encode_cursor(created_at: datetime, record_id: uuid.UUID) -> str:
    """Encode the last row's timestamp and UUID as an opaque client cursor."""
    data = json.dumps([created_at.isoformat(), str(record_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a cursor supplied by a list client or reject malformed input."""
    try:
        data = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        timestamp, record_id = json.loads(data)
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value, uuid.UUID(record_id)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def before_cursor(timestamp_column, id_column, cursor: str):
    """Build the keyset filter for a newest-first list query."""
    timestamp, record_id = decode_cursor(cursor)
    return or_(timestamp_column < timestamp, and_(timestamp_column == timestamp, id_column < record_id))
