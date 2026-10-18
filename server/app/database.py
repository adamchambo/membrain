"""PostgreSQL connection configuration for the server and migrations."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url


def database_url() -> URL:
    """Parse the database connection string supplied to the process."""
    return make_url(os.environ["DATABASE_URL"])


def create_db_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)
