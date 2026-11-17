"""Workflow request bodies. ``Expected`` carries the revision the caller saw."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from sm_events.core import constants
from sm_events.web.schemas._fields import MultiLine
from sm_events.web.schemas.events_in import Expected, Revision

__all__ = ["ApproveIn", "Expected", "RejectIn"]

Wall = Annotated[str, Field(max_length=40)]
RejectNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=constants.NOTE_MAX),
    MultiLine,
]


class ApproveIn(BaseModel):
    """``publish_at_local`` is ``YYYY-MM-DDTHH:MM`` on the event's own wall clock:
    absent or not in the future publishes now, a future one schedules."""

    expected_revision: Revision
    publish_at_local: Wall | None = None


class RejectIn(BaseModel):
    expected_revision: Revision
    note: RejectNote
