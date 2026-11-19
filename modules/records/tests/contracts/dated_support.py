"""Shared setup for the dated-records contract's tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sm_records.contracts.dated import (
    DatedCaller,
    dated_records,
)
from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordStatus
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow  # noqa: F401 - parity with other suites

from tests.support.app_harness import field

SETTINGS = RecordsSettings()
VIEW = "records.view"
LO, HI = date(2026, 7, 1), date(2026, 8, 1)
LO_T, HI_T = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)
FIELDS = [
    field("title", "text", indexed=False),
    field("due", "date"),
    field("at", "datetime"),
    field("until", "date"),
    field("ends", "datetime"),
    field("note", "text", indexed=False),
]


def caller(*roles: str, perms: tuple[str, ...] = (VIEW,), granted: tuple[str, ...] = ()):
    return DatedCaller(
        roles=tuple(roles),
        permissions=frozenset((*perms, *(f"records.type.{k}" for k in granted))),
        role_map=None,
    )


async def make_type(db, key="deadlines", **cols: Any):
    return await type_service.create_type(
        db, key=key, label=key, fields_raw=FIELDS, display_field="title", settings=SETTINGS, **cols
    )


async def add(db, rtype, title, due=None, at=None, status=RecordStatus.PUBLISHED, **extra):
    data = {"title": title}
    if due is not None:
        data["due"] = due
    if at is not None:
        data["at"] = at
    data.update(extra)
    return await record_service.create_record(
        db, rtype, data=data, settings=SETTINGS, status=status
    )


async def read(db, key="deadlines", who=caller(), **kw):
    kw.setdefault("lo", LO)
    kw.setdefault("hi", HI)
    kw.setdefault("field", "due")
    kw.setdefault("locale", None)
    kw.setdefault("limit", 100)
    return await dated_records(db, tenant_id="default", type_key=key, caller=who, **kw)
