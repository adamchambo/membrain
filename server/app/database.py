"""PostgreSQL connection configuration for the server and migrations."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL


def database_url() -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("ORACLE_DB_USER", "oracle"),
        password=os.environ["ORACLE_DB_PASSWORD"],
        host=os.environ.get("ORACLE_DB_HOST", "localhost"),
        port=int(os.environ.get("ORACLE_DB_PORT", "5432")),
        database=os.environ.get("ORACLE_DB_NAME", "oracle"),
    )


def create_db_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)
