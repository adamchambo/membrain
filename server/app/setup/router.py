import secrets
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import setting, remember_embedding_connection
from app.database import get_db
from app.setup import service, profiles
from app.setup.schemas import CapabilityCheck, MigrationRead, MigrationRequest, ProbeRead, ReadinessRead, SettingsRead, SetupConfiguration

router = APIRouter(tags=["setup"])
Db = Annotated[Session, Depends(get_db)]


def require_admin(x_oracle_setup_token: Annotated[str | None, Header()] = None):
    expected = setting("ORACLE_SETUP_TOKEN")
    if not expected or not x_oracle_setup_token or not secrets.compare_digest(expected, x_oracle_setup_token):
        raise HTTPException(403, "Set ORACLE_SETUP_TOKEN and supply X-Oracle-Setup-Token for setup administration")


@router.get("/api/v1/setup", response_model=SettingsRead)
def setup_status():
    return service.safe_settings()


@router.get("/health/ready", response_model=ReadinessRead)
def readiness():
    return service.readiness()


@router.put("/api/v1/setup", response_model=SettingsRead, dependencies=[Depends(require_admin)])
def save_setup(data: SetupConfiguration):
    return service.save_settings(data, allow_database_change=False)


@router.post("/api/v1/setup/validate", response_model=dict[str, ProbeRead], dependencies=[Depends(require_admin)])
def validate_setup(data: CapabilityCheck):
    return service.check_capabilities(data.capabilities)


@router.post("/api/v1/embedding-migrations", status_code=202, response_model=MigrationRead, dependencies=[Depends(require_admin)])
def start_migration(data: MigrationRequest, db: Db):
    if data.model != data.profile.model:
        raise HTTPException(422, "Endpoint model and profile model must match")
    remember_embedding_connection(data.profile.key, data.url, data.api_key.get_secret_value() if data.api_key else None)
    return profiles.start_migration(db, data.profile)


@router.get("/api/v1/embedding-migrations/{migration_id}", response_model=MigrationRead)
def get_migration(migration_id: UUID, db: Db):
    return profiles.migration_status(db, migration_id)


@router.post("/api/v1/embedding-migrations/{migration_id}/{action}", response_model=MigrationRead, dependencies=[Depends(require_admin)])
def decide_migration(migration_id: UUID, action: Literal["cutover", "cancel"], db: Db):
    return profiles.decide_migration(db, migration_id, action)
