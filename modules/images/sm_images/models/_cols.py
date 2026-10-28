"""Column helpers shared by the model files."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from simple_module_db.types import AwareDateTime
from sqlalchemy import JSON, Column, ForeignKey, Uuid
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from sm_images import constants


def utcnow() -> datetime:
    return datetime.now(UTC)


def pk_uuid() -> Any:
    """A client-generated UUID primary key (ids appear in storage keys and URLs)."""
    return Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))


def fk_uuid(target: str, *, nullable: bool = False, ondelete: str | None = None) -> Any:
    return Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True
        ),
    )


def enum_col(enum_cls: type[enum.Enum], suffix: str, default: enum.Enum) -> Any:
    """A Postgres enum named ``images_<suffix>`` (dropped by the migration's ``_drop_enums``)."""
    return Field(
        default=default,
        sa_column=Column(
            SAEnum(enum_cls, name=f"{constants.TABLE_PREFIX}{suffix}"), nullable=False
        ),
    )


def json_col(default_factory: Any) -> Any:
    return Field(
        default_factory=default_factory,
        sa_column=Column(JSON, nullable=False, default=default_factory),
    )


def json_null() -> Any:
    return Field(default=None, sa_column=Column(JSON, nullable=True))


def dt_col(*, index: bool = False) -> Any:
    """A nullable timezone-aware timestamp."""
    return Field(
        default=None, sa_type=AwareDateTime(), sa_column_kwargs={"nullable": True, "index": index}
    )
