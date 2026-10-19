"""PostgreSQL connection configuration for the server and migrations."""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session
from app.config import setting
from app.errors import NotConfigured


def database_url() -> URL:
    """Parse the database connection string supplied to the process."""
    value = setting("DATABASE_URL")
    if not value:
        raise NotConfigured("Database connection is not configured")
    return make_url(value)


def create_db_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


@lru_cache
def db_engine() -> Engine:
    """Create the shared engine only when a database route is first used."""
    return create_db_engine()


def get_db() -> Iterator[Session]:
    """Give one request a database session; services control transactions."""
    with Session(db_engine(), expire_on_commit=False) as session:
        yield session
