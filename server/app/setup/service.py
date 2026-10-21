"""Bootstrap persistence and probes never return credentials or provider bodies."""

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.ai.client import get_chat_client
from app.ai.embeddings import configured_profile, embed
from app.config import environment_value, config_lock, read_config, setting, write_config
from app.database import create_db_engine, db_engine
from app.errors import AppError, NotConfigured
from app.jobs.models import WorkItem
from app.setup.models import WorkerHeartbeat
from app.setup.schemas import SetupConfiguration


def migration_head():
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


def safe_settings() -> dict:
    return {"database_configured": bool(setting("DATABASE_URL")),
            "chat": {"configured": bool(setting("MEMBRAIN_CHAT_COMPLETIONS_URL") and setting("MEMBRAIN_CHAT_MODEL")), "model": setting("MEMBRAIN_CHAT_MODEL")},
            "embeddings": {"configured": bool(setting("MEMBRAIN_EMBEDDINGS_URL") and setting("MEMBRAIN_EMBEDDING_REVISION")), "model": setting("MEMBRAIN_EMBEDDING_MODEL", "nomic-embed-text-v1.5")}}


def save_settings(data: SetupConfiguration, *, allow_database_change: bool = True) -> dict:
    with config_lock():
        return save_settings_locked(data, allow_database_change=allow_database_change)


def save_settings_locked(data: SetupConfiguration, *, allow_database_change: bool) -> dict:
    if data.database_url is not None and not allow_database_change:
        current = setting("DATABASE_URL")
        if current and current != data.database_url.get_secret_value():
            raise NotConfigured("Stop the API and worker, then change databases using python -m app.setup")
    # Retain the previous profile connection so target configuration changes do
    # not disconnect query inference for the still-active profile.
    value = read_config()
    try:
        old = configured_profile()
        value.setdefault("embedding_connections", {})[old.key] = {"url": setting("MEMBRAIN_EMBEDDINGS_URL"), "api_key": setting("MEMBRAIN_EMBEDDING_API_KEY")}
    except NotConfigured:
        pass
    settings = value.setdefault("settings", {})
    if data.database_url is not None:
        from sqlalchemy.engine import make_url
        try:
            url = make_url(data.database_url.get_secret_value())
            if url.get_backend_name() != "postgresql":
                raise ValueError()
        except Exception as exc:
            raise NotConfigured("Setup requires a valid PostgreSQL connection URL") from exc
        settings["DATABASE_URL"] = data.database_url.get_secret_value()
    for name, endpoint in (("CHAT", data.chat), ("EMBEDDING", data.embeddings)):
        if ("chat" if name == "CHAT" else "embeddings") not in data.model_fields_set:
            continue
        url_key = "MEMBRAIN_CHAT_COMPLETIONS_URL" if name == "CHAT" else "MEMBRAIN_EMBEDDINGS_URL" if name == "EMBEDDING" else "MEMBRAIN_TRANSCRIPTION_URL"
        settings[url_key] = endpoint.url if endpoint else ""
        settings[f"MEMBRAIN_{name}_MODEL"] = endpoint.model if endpoint else ""
        settings[f"MEMBRAIN_{name}_API_KEY"] = endpoint.api_key.get_secret_value() if endpoint and endpoint.api_key else ""
    if "embeddings" in data.model_fields_set and data.embeddings:
        p = data.embeddings.profile
        if p.model != data.embeddings.model:
            raise NotConfigured("Embedding endpoint model and profile model must match")
        settings.update({"MEMBRAIN_EMBEDDING_REVISION": p.revision, "MEMBRAIN_EMBEDDING_DIMENSIONS": str(p.dimensions),
                         "MEMBRAIN_EMBEDDING_DOCUMENT_PREFIX": p.document_prefix, "MEMBRAIN_EMBEDDING_QUERY_PREFIX": p.query_prefix})
        value.setdefault("embedding_connections", {})[p.key] = {"url": data.embeddings.url,
            "api_key": data.embeddings.api_key.get_secret_value() if data.embeddings.api_key else None}
    elif "embeddings" in data.model_fields_set:
        # Explicit null disables embedding inference; omitted fields stay unchanged.
        value.pop("embedding_connections", None)
    if "database_mode" in data.model_fields_set:
        settings["MEMBRAIN_DATABASE_MODE"] = data.database_mode
    write_config(value)
    return {**safe_settings(), "environment_overrides": sorted(key for key, value in settings.items() if environment_value(key) and environment_value(key) != value)}


def check_capabilities(capabilities: list[str]) -> dict:
    result = {}
    for capability in capabilities:
        try:
            if capability == "database":
                engine = create_db_engine()
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                        if not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")):
                            raise NotConfigured("pgvector is not installed in the selected database")
                        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
                        if version != migration_head():
                            raise NotConfigured("Database migrations are behind the installed API")
                    result[capability] = {"ready": True, "migration": version}
                finally:
                    engine.dispose()
            elif capability == "chat":
                raw = get_chat_client().generate('Return only JSON: {"ok":true}', "Check the JSON response capability.")
                if json.loads(raw) != {"ok": True}:
                    raise NotConfigured("The conversation model did not satisfy the JSON probe")
                result[capability] = {"ready": True}
            elif capability == "embeddings":
                profile = configured_profile()
                vector = embed("A small setup check.", profile)
                result[capability] = {"ready": True, "profile_key": profile.key, "dimensions": len(vector)}
        except Exception as exc:
            result[capability] = {"ready": False, "detail": exc.message if isinstance(exc, AppError) else "The capability check failed"}
    return result


def readiness() -> dict:
    report = {"settings": safe_settings(), "database": {"ready": False}, "worker": {"ready": False}, "pending_work": {}}
    engine = None
    try:
        engine = create_db_engine()
        with engine.connect() as db:
            version = db.scalar(text("SELECT version_num FROM alembic_version"))
            report["database"] = {"ready": version == migration_head(), "migration": version}
            last = db.scalar(select(func.max(WorkerHeartbeat.seen_at)))
            report["worker"] = {"ready": bool(last and last > datetime.now(timezone.utc) - timedelta(seconds=150)), "last_seen_at": last}
            report["pending_work"] = dict(db.execute(select(WorkItem.status, func.count()).group_by(WorkItem.status)).all())
    except Exception:
        report["database"]["detail"] = "Database configuration, connectivity, or migrations are incomplete"
        report["database"]["ready"] = False
    finally:
        if engine:
            engine.dispose()
    return report
