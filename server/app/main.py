from fastapi import FastAPI

from app.errors import AppError, app_error_handler
from app.captures.router import router as captures_router
from app.knowledge.router import router as knowledge_router
from app.discovery.router import router as discovery_router
from app.routers.health import router as health_router

app = FastAPI(title="Oracle API")
app.add_exception_handler(AppError, app_error_handler)
app.include_router(health_router)
app.include_router(captures_router)
app.include_router(knowledge_router)
app.include_router(discovery_router)
