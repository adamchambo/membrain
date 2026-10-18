"""Single declarative registry for Oracle database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
