"""Typed adapter over the generated SDK. No terminal IO or provider credentials."""
from __future__ import annotations
from dataclasses import replace
import json
from threading import RLock
from uuid import UUID

import membrain_sdk as sdk
from membrain_sdk.exceptions import ApiException
from pydantic import ValidationError
from urllib3.exceptions import HTTPError

from .config import server_url
from .types import ClientError, Context, Item, Job, Result


def data(value):
    """Convert a generated wire model to JSON-compatible display data."""
    return value.to_dict() if hasattr(value, 'to_dict') else value


def required(value, label):
    if value is None:
        raise ClientError(f'Choose {label} first.')
    return value


from .commands.capture import CaptureCommands
from .commands.bank import BankCommands
from .commands.review import ReviewCommands
from .commands.learning import LearningCommands
from .commands.reflection import ReflectionCommands
from .commands.status import StatusCommands


class SDKBackend(CaptureCommands, BankCommands, ReviewCommands, LearningCommands, ReflectionCommands, StatusCommands):
    is_stub = False

    def __init__(self, url: str, client=None, jobs: list[Job] | None = None):
        """Connect to url; client injects an SDK transport for tests, jobs restores known IDs."""
        self.url = server_url(url)
        config = sdk.Configuration(host=self.url)
        config.retries = 0
        self.client = client or sdk.ApiClient(config)
        self.lock = RLock()
        self.tracked = {job.id: job for job in jobs or []}
        for name, cls in [('captures', sdk.CapturesApi), ('knowledge', sdk.KnowledgeApi),
                          ('discovery', sdk.DiscoveryApi), ('review', sdk.ReviewApi),
                          ('subjects', sdk.SubjectsAndReflectionApi), ('learning', sdk.LearningApi),
                          ('management', sdk.BankManagementApi), ('setup', sdk.SetupApi),
                          ('work', sdk.JobsApi), ('sources', sdk.SourceContentApi)]:
            setattr(self, name, cls(self.client))

    def execute(self, function, *args, **kwargs):
        """Call SDK function with args/kwargs, bounded timeouts and safe errors."""
        kwargs.setdefault('_request_timeout', (2.0, 5.0))
        try:
            with self.lock:
                return function(*args, **kwargs)
        except ApiException as error:
            detail = f'API request failed ({error.status}).'
            try:
                body = json.loads(error.body or '{}')
                problem = body.get('detail')
                if isinstance(problem, str):
                    detail = problem
                elif isinstance(problem, list):
                    detail = '; '.join(f"{'.'.join(map(str, item.get('loc', [])))}: {item.get('msg', 'invalid value')}" for item in problem)
            except (ValueError, TypeError):
                pass
            raise ClientError(detail) from None
        except ValidationError as error:
            raise ClientError('; '.join('.'.join(map(str, item['loc'])) + ': ' + item['msg'] for item in error.errors(include_input=False))) from None
        except (HTTPError, OSError, TimeoutError):
            raise ClientError(f'Cannot reach the API at {self.url}. Start the local API or check the server address.') from None

    def close(self):
        self.client.rest_client.pool_manager.clear()

    def readiness(self):
        return self.execute(self.setup.readiness)

    def queue(self, message: str, context: Context, job: Job) -> Result:
        job = replace(job, status='pending')
        self.tracked[job.id] = job
        return Result(message + f' Work ID: {job.id}', replace(context, job_id=job.id), job=job)

    def concepts(self, cursor=None):
        return self.execute(self.knowledge.list_concepts, limit=100, cursor=cursor)

    def scope_ids(self, context: Context, maximum: int = 20) -> list[UUID]:
        """Resolve selected context to concept IDs, enforcing maximum per API operation."""
        ids = list(context.concept_ids) or ([context.concept_id] if context.concept_id else [])
        if context.subject_id:
            ids = self.execute(self.subjects.subject_scope, context.subject_id).concept_ids
        if not ids:
            raise ClientError('Choose a concept or a subject containing saved concepts first.')
        if len(ids) > maximum:
            raise ClientError(f'This activity supports at most {maximum} concepts. Choose a narrower scope.')
        return ids

    def task(self, kind: str, question: str, context: Context) -> Result:
        scoped = bool(context.subject_id or context.concept_id or context.concept_ids)
        ids = self.scope_ids(context) if scoped else []
        if not ids and (kind not in ('clarification', 'lesson', 'worked_example', 'diagram') or not question.strip()):
            raise ClientError('Choose a concept or enter an explicit question first.')
        receipt = self.execute(self.learning.create_task, sdk.TaskCreate(
            kind=kind, concept_ids=ids, question=question,
            resource_ids=[context.resource_id] if context.resource_id else [],
            parent_artifact_id=context.artifact_id if kind in ("clarification", "lesson", "worked_example", "diagram") else None))
        context = replace(context, artifact_id=receipt.artifact_id, suggestion_id=None, question=question)
        return self.queue('Learning task queued. Generated material stays separate from your understanding.',
                          context, Job(receipt.job_id, 'learning', receipt.artifact_id))

    def call(self, operation: str, text: str, context: Context, *, cursor=None) -> Result:
        """Perform operation using entered text and typed context; cursor continues a list."""
        if operation.startswith('capture.') or operation.startswith('chat.'):
            return self._capture(operation, text, context, cursor)
        if operation.startswith(('bank.', 'scope.', 'subject.')):
            return self._bank(operation, text, context, cursor)
        if operation.startswith('review.'):
            return self._review(operation, text, context)
        if operation.startswith(('gap.', 'clarify.', 'learn.', 'suggestion.', 'artifact.')):
            return self._learning(operation, text, context)
        if operation.startswith('reflect.'):
            return self._reflect(operation, text, context)
        if operation.startswith('jobs.'):
            return self._jobs(operation, text, context)
        raise ClientError(f'Unsupported CLI operation: {operation}')







    def poll(self, job: Job, context: Context) -> tuple[str, Result]:
        """Inspect job and return terminal results using its saved context."""
        work = self.execute(self.work.get_job, job.id)
        context = replace(context, job_id=job.id)
        if work.status == 'succeeded' and job.target:
            if job.kind == 'capture':
                row = self.execute(self.captures.get_capture, job.target)
                return work.status, Result('Capture organization completed.', context, payload=data(row))
            if job.kind == 'learning':
                context = replace(context, artifact_id=job.target)
                return work.status, self._learning('artifact.inspect', '', context)
            if job.kind == 'review_feedback':
                row = self.execute(self.review.get_attempt, job.target)
                return work.status, Result('Recall feedback; factual correctness remains unverified.', replace(context, attempt_id=job.target), payload=data(row))
        message = f'Work {job.id}: {work.status}'
        if work.last_error:
            message += f' — {work.last_error}. Use Processing status to retry.'
        return work.status, Result(message, context, payload=data(work))
