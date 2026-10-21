"""Single declarative registry for Membrain database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
