"""A fake plugin package: source ``acme:talks`` and type ``acme:talk``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sm_events.contracts.extensions import EventType


class TalkExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    room: str | None = None
    level: Literal["intro", "advanced"] = "intro"


class TalksSource:
    id = "acme:talks"
    label_key = "acme.talks"
    public = False
    color = "#112233"
    icon = "mic"
    settings_model = None

    async def occurrences(self, ctx, start, end):
        return []


TALK = EventType(
    id="acme:talk",
    label_key="acme.types.talk",
    extra_model=TalkExtra,
    public_fields=frozenset({"speaker"}),
    icon="mic",
)


def register(registry) -> None:
    registry.add_source(TalksSource())
    registry.add_type(TALK)
