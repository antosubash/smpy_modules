"""Site layout — the header and footer that wrap every public page."""

from __future__ import annotations

from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column
from sqlmodel import Field

from pagebuilder.models._base import Base


class Layout(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Singleton — :meth:`LayoutService.get` creates the row on first read."""

    __tablename__ = "pagebuilder_layout"

    id: int | None = Field(default=None, primary_key=True)
    header_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    footer_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )


class LayoutRevision(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "pagebuilder_layout_revisions"

    id: int | None = Field(default=None, primary_key=True)
    layout_id: int = Field(foreign_key="pagebuilder_layout.id", index=True)
    header_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    footer_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    note: str | None = Field(default=None, max_length=2000)


