"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import membrain_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class ReflectionCommands:
    def _reflect(self, operation, text, context):
        def timestamp(raw):
            if not raw:
                return None
            try:
                value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except ValueError:
                raise ClientError('Use an ISO timestamp with timezone, for example 2026-10-01T00:00:00+11:00.') from None
            if value.tzinfo is None:
                raise ClientError('Include the timezone offset in reflection timestamps.')
            return value
        result = self.execute(self.subjects.reflect, subject_id=context.subject_id,
                              since=timestamp(context.since), until=timestamp(context.until))
        return Result('Recorded changes and review evidence; unreviewed does not mean unknown.',
                      replace(context, reflection_concept_ids=tuple(dict.fromkeys(row.concept_id for row in result.revisions))), payload=data(result))
