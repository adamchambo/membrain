"""Domain command handlers using the adapter's generated SDK clients."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
import random
from uuid import UUID
import membrain_sdk as sdk
from ..types import ClientError, Context, Item, Job, Result


from . import data, required


class StatusCommands:
    def _jobs(self, operation, text, context):
        if operation.startswith('jobs.list.'):
            group = operation.rsplit('.', 1)[-1]
            states = {'pending': {'pending', 'running'}, 'failed': {'failed', 'cancelled'}, 'completed': {'succeeded'}}[group]
            rows = []
            for job in list(self.tracked.values())[-100:]:
                work = self.execute(self.work.get_job, job.id)
                if work.status in states:
                    rows.append(Item(job.id, 'job', f'{work.kind}: {work.status}', work.last_error or ''))
            return Result('Jobs seen by this client (last 100); paste another job UUID to inspect it.', context, tuple(rows))
        if operation == 'jobs.readiness':
            return Result('Server readiness:', context, payload=data(self.readiness()))
        identifier = context.job_id or (UUID(text) if text else None)
        if operation == 'jobs.select':
            identifier = UUID(text)
        identifier = required(identifier, 'a job')
        if operation == 'jobs.retry':
            work = self.execute(self.work.retry_job, identifier)
            job = self.tracked.get(identifier, Job(identifier, work.kind))
            return self.queue('Work scheduled for retry.', context, job)
        if operation == 'jobs.readiness':
            return Result('Server readiness:', context, payload=data(self.readiness()))
        work = self.execute(self.work.get_job, identifier)
        context = replace(context, job_id=work.id)
        if operation == 'jobs.result' and work.status == 'succeeded' and identifier in self.tracked:
            return self.poll(self.tracked[identifier], context)[1]
        return Result('Work record:', context, payload=data(work))
