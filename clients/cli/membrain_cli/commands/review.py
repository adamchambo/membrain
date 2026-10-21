"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import membrain_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class ReviewCommands:
    def _review(self, operation, text, context):
        if operation == 'review.history':
            history = self.execute(self.subjects.review_history, limit=100)
            return Result('Unfinished reviews (newest 100 sessions):', context, tuple(Item(row.id, 'review_session', f'{row.mode} — {row.started_at}') for row in history.items if row.finished_at is None))
        if operation == 'review.resume':
            import json
            history = self.execute(self.subjects.review_history, limit=100)
            row = next((row for row in history.items if str(row.id) == text and row.finished_at is None), None)
            if row is None:
                raise ClientError('Choose an unfinished review from the displayed recent sessions.')
            context = replace(context, subject_id=None, concept_id=None, concept_ids=tuple(UUID(value) for value in json.loads(row.requested_scope)), mode=row.mode, review_session_id=row.id, question_id=None)
            return self._review('review.next', '', context)
        if operation == 'review.suggest':
            report = self.execute(self.subjects.reflect)
            ids = report.unreviewed_concept_ids or report.eligible_concept_ids
            if not ids:
                raise ClientError('Capture an explanation before starting a review.')
            concept = self.execute(self.knowledge.get_concept, ids[0])
            return Result('Suggested because it is unreviewed, or the first eligible concept; mastery is not inferred.', context.scope(concept=concept.id, label=concept.title))
        if operation in ('review.begin', 'review.question', 'review.next'):
            if context.review_session_id is None:
                ids = self.scope_ids(context, maximum=200)
                session = self.execute(self.review.create_session, sdk.SessionCreate(concept_ids=ids, mode=context.mode))
                context = replace(context, review_session_id=session.id, concept_ids=tuple(session.concept_ids))
            if operation == 'review.begin':
                return Result('Review session created.', context)
            question = self.execute(self.review.next_question, context.review_session_id, _request_timeout=(2.0, 45.0))
            context = replace(context, question_id=question.id)
            return Result('Answer before viewing the earlier explanation.', context, prompt=question.prompt)
        if operation == 'review.answer':
            attempt = self.execute(self.review.record_attempt, required(context.review_session_id, 'a review session'),
                                   sdk.AttemptCreate(question_id=required(context.question_id, 'a question'), response=text))
            context = replace(context, attempt_id=attempt.id)
            if attempt.feedback_job_id:
                return self.queue('Saved your answer; recall feedback is processing.', context, Job(attempt.feedback_job_id, 'review_feedback', attempt.id))
            return Result('Saved answer.', context, payload=data(attempt))
        if operation == 'review.finish':
            identifier = required(context.review_session_id, 'a review session')
            self.execute(self.review.finish_session, identifier)
            result = self.execute(self.subjects.session_detail, identifier)
            return Result('Review finished. Questions and answers cover only the selected scope; mastery is not inferred.',
                          replace(context, review_session_id=None, question_id=None), payload=data(result))
        raise ClientError('Unknown review action.')
