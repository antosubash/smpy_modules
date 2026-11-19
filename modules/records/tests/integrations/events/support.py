"""Fixtures for the events source's tests: a type with dates, and a hand-built source context."""

from __future__ import annotations

import uuid
from typing import Any

from sm_events.contracts.extensions import SourceCalendar, SourceContext, SourceViewer
from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordStatus
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service

from tests.support.app_harness import field

SETTINGS = RecordsSettings(content_locales=("en", "de"))
FIELDS = [
    field("title", "text", indexed=False),
    field("due", "date"),
    field("at", "datetime"),
    field("until", "date"),
    field("ends", "datetime"),
]
CALENDAR = SourceCalendar(
    id=uuid.uuid4(),
    slug="team",
    name="Team",
    visibility="internal",
    default_timezone="Europe/Vienna",
    color="#2563eb",
)


def viewer(*roles: str, perms: tuple[str, ...] = ("records.view",)) -> SourceViewer:
    return SourceViewer(
        user_id="u1", roles=tuple(roles), permissions=frozenset(perms), role_map=None
    )


def context(db: Any, settings: Any, who: SourceViewer | None, *, limit: int = 500) -> SourceContext:
    return SourceContext(
        tenant_id="default",
        viewer=who,
        calendar=CALENDAR,
        settings=settings,
        locale="en",
        default_locale="en",
        limit=limit,
        db=db,
    )


async def make_type(db: Any, key: str = "deadlines", **cols: Any):
    return await type_service.create_type(
        db,
        key=key,
        label=key.title(),
        fields_raw=FIELDS,
        display_field="title",
        settings=SETTINGS,
        **cols,
    )


async def add(db: Any, rtype: Any, title: str, status=RecordStatus.PUBLISHED, **data: Any):
    return await record_service.create_record(
        db, rtype, data={"title": title, **data}, settings=SETTINGS, status=status
    )
