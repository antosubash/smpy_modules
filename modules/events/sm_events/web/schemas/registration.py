"""Registration settings in event bodies and responses (PR 9).

The body speaks a local wall clock (``opens_at_local``) in the event's own timezone and never UTC,
like every time in this API. ``RegistrationIn`` is a full replacement of an event's settings; one
that arrives with a PATCH replaces them whole. The response model has no input bounds: a stored
row always renders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from sm_events.core import constants
from sm_events.web.schemas._fields import HttpUrl, SingleLine

__all__ = ["RegistrationCountOut", "RegistrationCountsOut", "RegistrationIn", "RegistrationOut"]

Provider = Annotated[str, Field(min_length=1, max_length=constants.REGISTRATION_PROVIDER_MAX)]
Target = Annotated[
    str, Field(min_length=1, max_length=constants.REGISTRATION_TARGET_MAX), SingleLine
]
Capacity = Annotated[int, Field(ge=1, le=constants.REGISTRATION_CAPACITY_MAX)]
Wall = Annotated[str, Field(max_length=constants.TIMES_FIELD_MAX)]
Lead = Annotated[int, Field(ge=0, le=2**31 - 1)]


class RegistrationIn(BaseModel):
    """What an event offers for registering. ``external`` needs ``url``; ``builtin`` needs a
    ``provider`` and a ``target`` (the form's name, opaque to events); only ``builtin`` takes a
    capacity, a window, ``show_seats`` and a reminder lead. Anything else set is a 422."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal[*constants.REGISTRATION_MODES] = constants.REGISTRATION_MODE_NONE  # type: ignore[valid-type]
    url: HttpUrl | None = None
    provider: Provider | None = None
    target: Target | None = None
    capacity: Capacity | None = None
    opens_at_local: Wall | None = None
    closes_at_local: Wall | None = None
    show_seats: bool = False
    reminder_minutes: Lead | None = None


class RegistrationOut(BaseModel):
    mode: str
    url: str | None
    provider: str | None
    target: str | None
    capacity: int | None
    opens_at_local: str | None
    closes_at_local: str | None
    show_seats: bool
    reminder_minutes: int | None
    target_hidden: bool = False
    """The editor may edit this event but not read the form it registers into: ``provider`` and
    ``target`` are withheld, the form cannot be changed by them, and a save leaves it as it is."""
    provider_installed: bool | None
    """``None`` unless the mode is ``builtin``; ``False`` when this host has no such provider:
    the settings are kept as they are and cannot be changed until it is back."""


class RegistrationCountOut(BaseModel):
    """Seats taken at one occurrence. Counts only: who holds them is the provider's business."""

    occurrence_key: str
    start: datetime | None
    """``None`` for an occurrence that no longer exists on the calendar (skipped, say) but still
    holds seats."""
    start_local: str | None
    taken: int
    capacity: int | None


class RegistrationCountsOut(BaseModel):
    items: list[RegistrationCountOut]
    total: int
