"""Column helpers shared by the model files."""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_db.types import AwareDateTime
from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, Uuid
from sqlmodel import Field

from sm_events.core.clock import utcnow

# BIGINT on Postgres; SQLite only autoincrements an ``INTEGER PRIMARY KEY``.
_BIG = BigInteger().with_variant(Integer, "sqlite")


def big_pk() -> Any:
    """An autoincrementing 64-bit key, for the tables that grow per event."""
    return Field(default=None, sa_column=Column(_BIG, primary_key=True, autoincrement=True))


def pk_uuid() -> Any:
    """A client-generated UUID primary key (ids appear in URLs and share rows)."""
    return Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))


def fk_uuid(target: str, *, nullable: bool = False, ondelete: str | None = None) -> Any:
    """An indexed foreign key to a UUID-keyed table."""
    return Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True
        ),
    )


def dt_col(*, nullable: bool = True) -> Any:
    """A timezone-aware timestamp. A ``NOT NULL`` one defaults to now (UTC),
    Python-side, so it never depends on the database's clock."""
    kwargs: dict[str, Any] = {"default_factory": utcnow} if not nullable else {"default": None}
    return Field(**kwargs, sa_type=AwareDateTime(), sa_column_kwargs={"nullable": nullable})


def dt_required() -> Any:
    """A timezone-aware ``NOT NULL`` timestamp the caller must supply."""
    return Field(sa_type=AwareDateTime(), sa_column_kwargs={"nullable": False})


def json_col(default_factory: Any) -> Any:
    return Field(
        default_factory=default_factory,
        sa_column=Column(JSON, nullable=False, default=default_factory),
    )


def flag() -> Any:
    """A ``NOT NULL`` boolean."""
    return Field(default=False, sa_column_kwargs={"nullable": False})
