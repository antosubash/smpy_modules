"""What a preset's ``cross_check`` sees: frozen read models, no ORM, no session.

A cross-check is ``cross_check(group, results) -> dict`` (spec §8.3):

* ``group`` - :class:`GroupRead`, its members in the collection's role order;
* ``results`` - one :class:`PromptResultRead` per member whose image-scope
  result was usable (role order), then **the group's own consolidated
  result last** (``group_id`` set, ``image_id`` ``None``), so a check can
  compare the summary with the per-member answers.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = ["GroupMemberRead", "GroupRead", "PromptResultRead"]


class GroupMemberRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    image_id: uuid.UUID
    role: str | None = None
    filename: str


class GroupRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    key: str
    name: str | None = None
    members: tuple[GroupMemberRead, ...] = ()


class PromptResultRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_id: uuid.UUID
    image_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    role: str | None = None
    """The member's role (``None`` for the group's own result)."""
    result_data: dict[str, Any] | None = None
    result_text: str | None = None
    model_name: str | None = None
    prompt_revision: int | None = None
