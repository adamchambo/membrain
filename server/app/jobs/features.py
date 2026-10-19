"""Feature work shares the worker's lease fencing and retry policy."""

from sqlalchemy.orm import Session

from app.jobs.models import WorkItem
from app.jobs.worker import owned_job


def process_feature(engine, job_id, token, kind):
    if kind == "resource_extract":
        from app.resources import service
        compute = service.extract
    elif kind == "learning":
        from app.learning import service
        compute = service.generate
    else:
        raise ValueError("Unsupported work kind")
    with Session(engine) as db:
        job = db.get(WorkItem, job_id)
        prepared = service.prepare(db, job.arguments)
    # Session is closed before extraction or inference begins.
    output = compute(prepared)
    with Session(engine) as db, db.begin():
        job = owned_job(db, job_id, token)
        if job is None:
            return
        job.result = service.apply(db, prepared, output)
        job.status, job.last_error = "succeeded", None
        job.lease_token, job.lease_until = None, None
