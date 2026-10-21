from fastapi import FastAPI

from app.errors import AppError, app_error_handler
from app.captures.router import router as captures_router
from app.knowledge.router import router as knowledge_router
from app.discovery.router import router as discovery_router
from app.jobs.router import router as jobs_router
from app.review.router import router as review_router
from app.routers.health import router as health_router
from app.setup.router import router as setup_router
from app.knowledge.management_router import router as management_router
from app.resources.router import router as resources_router
from app.learning.scope_router import router as scope_router
from app.learning.router import router as learning_router
from app.discovery.map_router import router as map_router
from app.portability.router import router as portability_router
from app.knowledge.deletion import router as deletion_router

from app.http_contract import ERROR_RESPONSES, operation_id

app = FastAPI(title="Membrain API", version="0.1.0",
              generate_unique_id_function=operation_id, responses=ERROR_RESPONSES,
              servers=[{"url": "http://127.0.0.1:8000", "description": "Local default; override in client configuration."}])
app.add_exception_handler(AppError, app_error_handler)
app.include_router(health_router)
app.include_router(captures_router)
app.include_router(knowledge_router)
app.include_router(discovery_router)
app.include_router(jobs_router)
app.include_router(review_router)
app.include_router(setup_router)
app.include_router(management_router)
app.include_router(resources_router)
app.include_router(scope_router)
app.include_router(learning_router)
app.include_router(map_router)
app.include_router(portability_router)
app.include_router(deletion_router)
