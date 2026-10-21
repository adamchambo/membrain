"""Verify pg_dump/pg_restore against disposable databases only."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.models import Base


def pg_environment(url):
    value = make_url(url)
    return {**os.environ, "PGHOST": value.host or "localhost", "PGPORT": str(value.port or 5432),
            "PGUSER": value.username or "", "PGPASSWORD": value.password or "", "PGDATABASE": value.database or ""}


def fingerprint(engine):
    with engine.connect() as db:
        return {name: hashlib.sha256(json.dumps(sorted([dict(row) for row in db.execute(select(table)).mappings()],
            key=lambda row: str(tuple(row[c.name] for c in table.primary_key))), sort_keys=True, default=str).encode()).hexdigest()
            for name, table in Base.metadata.tables.items()}


def verify(admin_url, source_url):
    if not (make_url(source_url).database or "").startswith("membrain_test_"):
        raise RuntimeError("Backup verification requires a disposable source database")
    directory = Path(os.getenv("MEMBRAIN_PG_BIN", "/opt/homebrew/opt/postgresql@18/bin"))
    dump = shutil.which("pg_dump") or str(directory / "pg_dump")
    restore = shutil.which("pg_restore") or str(directory / "pg_restore")
    if not Path(dump).is_file() or not Path(restore).is_file():
        raise RuntimeError("Set MEMBRAIN_PG_BIN to matching PostgreSQL backup utilities")
    name = "membrain_test_restore_" + uuid4().hex
    url = make_url(admin_url).set(database=name)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    source = create_engine(source_url)
    restored = create_engine(url)
    quoted = admin.dialect.identifier_preparer.quote(name)
    created = False
    try:
        with admin.connect() as db:
            db.execute(text(f"CREATE DATABASE {quoted}"))
            created = True
        with tempfile.TemporaryDirectory() as temporary:
            archive = str(Path(temporary) / "bank.dump")
            subprocess.run([dump, "--format=custom", "--no-owner", "--no-acl", "--file", archive],
                env=pg_environment(source_url), check=True, capture_output=True)
            subprocess.run([restore, "--no-owner", "--no-acl", "--exit-on-error", "--dbname", name, archive],
                env=pg_environment(url), check=True, capture_output=True)
        if fingerprint(source) != fingerprint(restored):
            raise RuntimeError("Restored content differs from the source fixture")
        print("Database backup/restore round trip: all mapped table contents match", flush=True)
    finally:
        source.dispose()
        restored.dispose()
        if created:
            with admin.connect() as db:
                db.execute(text(f"DROP DATABASE {quoted} WITH (FORCE)"))
        admin.dispose()
