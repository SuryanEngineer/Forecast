"""Declarative base shared by every model. Import every model module in
alembic/env.py so autogenerate can see them (see that file)."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
