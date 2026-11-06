"""Column helpers shared by the model files."""

from __future__ import annotations

from typing import Any

from simple_module_db.types import AwareDateTime
from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, text
from sqlmodel import Field

from sm_newsletter.core.clock import utcnow

STATUS_LEN = 24

# BIGINT on Postgres; SQLite only autoincrements an ``INTEGER PRIMARY KEY``.
_BIG = BigInteger().with_variant(Integer, "sqlite")


def big_pk() -> Any:
    """An autoincrementing 64-bit key, for the tables that grow per recipient."""
    return Field(default=None, sa_column=Column(_BIG, primary_key=True, autoincrement=True))


def fk(target: str, *, ondelete: str, nullable: bool = False, big: bool = False) -> Any:
    """An indexed foreign key; ``big`` for a target keyed by :func:`big_pk`."""
    return Field(
        default=None,
        sa_column=Column(
            _BIG if big else Integer,
            ForeignKey(target, ondelete=ondelete),
            nullable=nullable,
            index=True,
        ),
    )


def dt_col(*, index: bool = False, nullable: bool = True) -> Any:
    """A timezone-aware timestamp. A ``NOT NULL`` one defaults to now (UTC),
    Python-side, so it never depends on the database's clock."""
    kwargs: dict[str, Any] = {"default_factory": utcnow} if not nullable else {"default": None}
    return Field(
        **kwargs, sa_type=AwareDateTime(), sa_column_kwargs={"nullable": nullable, "index": index}
    )


def json_col(default_factory: Any, *, server_default: str | None = None) -> Any:
    return Field(
        default_factory=default_factory,
        sa_column=Column(
            JSON,
            nullable=False,
            default=default_factory,
            server_default=text(server_default) if server_default else None,
        ),
    )


def counter() -> Any:
    """A ``NOT NULL`` integer starting at 0."""
    return Field(default=0, sa_column_kwargs={"nullable": False})
