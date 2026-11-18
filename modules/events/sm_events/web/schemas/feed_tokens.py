"""Private feed link bodies (bounded) and responses (not, and never the token or its digest)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from sm_events.core import constants
from sm_events.web.schemas._fields import SingleLine

Label = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=constants.TOKEN_LABEL_MAX),
    SingleLine,
]


class TokenCreate(BaseModel):
    label: Label
    locale: str | None = Field(default=None, max_length=constants.LOCALE_MAX)


class TokenOut(BaseModel):
    """A link as listed: who holds it and when it was last used, never what opens it."""

    id: uuid.UUID
    label: str
    locale: str
    created_at: datetime
    last_used_at: datetime | None
    user_id: str
    user_name: str | None
    mine: bool


class TokenCreated(TokenOut):
    """The one response that carries the link: shown once, never stored."""

    url: str
    webcal_url: str
