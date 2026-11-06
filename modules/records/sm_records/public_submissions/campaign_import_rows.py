"""One import row against the record holding its address (newsletter PR 7, R3, R4, D5).

=================  ======================================  =======================
Record             *confirmed* row                         *unsubscribed* row
=================  ======================================  =======================
none               create ``confirmed`` (R4): ``created``  create ``unsubscribed``,
                                                           email only:
                                                           ``created_unsubscribed``
``confirmed``      new tags appended, empty fields         ``opt_in.leave`` with the
                   filled, validated: ``updated`` /        row's cutoff:
                   ``unchanged``                           ``unsubscribed`` /
                                                           ``kept_confirmed``
``pending``        ``kept_pending``                        ``kept_pending``
``unsubscribed``   ``kept_unsubscribed``                   ``kept_unsubscribed``
in the trash       ``trashed``                             ``trashed``
=================  ======================================  =======================

An existing record is decided under PR 6's row lock (``row_lock.lock_record``,
which ``opt_in.leave`` takes too), never written by ``transition`` or the
direct merge: a merge is ``update_record``, which validates (D5). Every write
runs in a savepoint. A value records refuses is dropped from the row's *new*
values and the write tried once more (``dropped`` names it); the stored value
stays. A ``Conflict`` (a concurrent signup claimed the address, the row moved)
re-reads the address and decides once more; a second one is ``invalid``.
Nothing here ever writes ``pending -> confirmed`` or resubscribes anyone.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core import locales
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.public_submissions import campaign_lists, opt_in, subscribe
from sm_records.public_submissions.campaign_reads import stored_tags
from sm_records.public_submissions.campaign_writes import TAGS, _holds, _merged
from sm_records.public_submissions.definition import EMAIL_KEY
from sm_records.public_submissions.row_lock import lock_record
from sm_records.public_submissions.subscribe import CONFIRMED, PENDING, UNSUBSCRIBED
from sm_records.public_submissions.system import _ordinary
from sm_records.records.services import records as record_service
from sm_records.records.services.errors import Conflict, ValidationFailed

__all__ = ["CONSENT_TEMPLATE", "apply"]

CONSENT_TEMPLATE = "Imported from {source} on {date}"
_KEY = re.compile(r"[^\[.]+")


class _Values:
    """A row's new ordinary values, and the keys dropped from them so far."""

    def __init__(self, rtype: RecordType, row: Any) -> None:
        self.values: dict[str, Any] = {}
        self.dropped: list[str] = []
        if row.status != CONFIRMED:
            return  # an unsubscribed record keeps no ordinary values
        mappable = {f["key"]: f for f in campaign_lists.mappable_fields(rtype)}
        for key, raw in row.fields.items():
            text = raw.strip() if isinstance(raw, str) else ""
            if not text:
                continue
            spec = mappable.get(key)
            if spec is None:
                self.dropped.append(str(key))
            else:
                self.values[key] = _choice(spec, text) if spec.get("type") == "select" else text
        tags = list(dict.fromkeys(t for t in row.tags if isinstance(t, str)))
        if tags and any(f.get("key") == TAGS for f in rtype.fields or [] if isinstance(f, dict)):
            self.values[TAGS] = tags
        elif tags:
            self.dropped.append(TAGS)

    def drop(self, exc: ValidationFailed) -> bool:
        """Drop the new values ``exc`` names; whether anything was dropped."""
        named = {m.group(0) for e in exc.errors if (m := _KEY.match(str(e.get("field", ""))))}
        bad = [key for key in self.values if key in named]
        for key in bad:
            del self.values[key]
            self.dropped.append(key)
        return bool(bad)


def _choice(spec: dict[str, Any], text: str) -> str:
    """A select value given as its value or its label: the value."""
    choices = [c for c in (spec.get("options") or {}).get("choices") or [] if isinstance(c, dict)]
    if any(c.get("value") == text for c in choices):
        return text
    by_label = [c.get("value") for c in choices if c.get("label") == text]
    return str(by_label[0]) if by_label else text


def _system(row: Any, email: str, now: datetime, settings: RecordsSettings, source: str):
    """R4: every system value an imported record starts with."""
    values: dict[str, Any] = {
        EMAIL_KEY: email,
        "sm_locale": locales.default(settings),
        "sm_nonce": secrets.token_hex(16),
        "sm_source_page": None,
        "sm_consent_ip_hash": None,
        "sm_confirm_sent_at": None,
        "sm_consent_text": None,
        "sm_consent_at": None,
        "sm_confirmed_at": None,
        "sm_unsubscribed_at": None,
    }
    if row.status == UNSUBSCRIBED:
        return {
            **values,
            "sm_status": UNSUBSCRIBED,
            "sm_unsubscribed_at": _until(row.unsubscribed_at, now),
        }
    day = now.astimezone(UTC).date().isoformat()
    return {
        **values,
        "sm_status": CONFIRMED,
        "sm_consent_text": CONSENT_TEMPLATE.format(source=source, date=day),
        "sm_consent_at": _until(row.consent_at, now),
        "sm_confirmed_at": _until(row.confirmed_at or row.consent_at, now),
    }


def _until(moment: datetime | None, now: datetime) -> datetime:
    """``moment``, else ``now``; never later than ``now``."""
    return now if moment is None or moment > now else moment


def _kept(record: Record) -> str | None:
    """The outcome for a record the import must not write; ``None`` for a
    live confirmed one."""
    if record.is_deleted:
        return "trashed"
    status = (record.data or {}).get("sm_status")
    if status == CONFIRMED:
        return None
    return {PENDING: "kept_pending", UNSUBSCRIBED: "kept_unsubscribed"}.get(status, "invalid")


async def _settle(db: AsyncSession, rtype: RecordType) -> None:
    """After a savepoint rolled back: reload the type if it was expired (on
    SQLite the type lock writes the type row), inside the greenlet."""
    if inspect(rtype).expired_attributes:
        await db.refresh(rtype)


async def _create(db, rtype, row, email, new: _Values, settings, now, source) -> str:
    system = _system(row, email, now, settings, source)
    for _ in range(2):
        try:
            async with db.begin_nested():
                await record_service.create_record(
                    db,
                    rtype,
                    data=dict(new.values),
                    settings=settings,
                    status=RecordStatus.DRAFT,
                    system=system,
                )
        except ValidationFailed as exc:
            await _settle(db, rtype)
            if not new.drop(exc):
                return "invalid"
            continue
        return "created" if row.status == CONFIRMED else "created_unsubscribed"
    return "invalid"


def _merge(rtype: RecordType, record: Record, values: dict[str, Any]) -> dict[str, Any]:
    """The stored ordinary values, new tags appended, empty fields filled."""
    stored = _ordinary(rtype, record)
    out = dict(stored)
    for key, value in values.items():
        if key == TAGS:
            tags = _merged(stored.get(TAGS), value, ())
            if tags != stored_tags(stored.get(TAGS)):
                out[TAGS] = tags
        elif stored.get(key) in (None, ""):
            out[key] = value
    return out


async def _update(db, rtype, record: Record, new: _Values, settings) -> str:
    """D5: the merge, validated, under the row lock the caller holds."""
    for _ in range(2):
        merged = _merge(rtype, record, new.values)
        if merged == _ordinary(rtype, record):
            return "unchanged"
        try:
            async with db.begin_nested():
                await record_service.update_record(
                    db,
                    rtype,
                    record,
                    expected_version=record.version,
                    data=merged,
                    settings=settings,
                )
        except ValidationFailed as exc:
            await _settle(db, rtype)
            record = await lock_record(db, rtype, record)
            if not new.drop(exc):
                return "invalid"
            continue
        return "updated"
    return "invalid"


async def _decide(db, rtype, row, email, record, new: _Values, settings, now, source) -> str:
    if record is None:
        return await _create(db, rtype, row, email, new, settings, now, source)
    record = await lock_record(db, rtype, record)
    kept = _kept(record)
    if kept is not None:
        return kept
    if row.status == UNSUBSCRIBED:
        cutoff = None if row.unsubscribed_at is None else _until(row.unsubscribed_at, now)
        async with db.begin_nested():
            outcome = await opt_in.leave(db, rtype, record, settings, still=_holds(cutoff))
        if outcome.wrote:
            return "unsubscribed"
        return _kept(outcome.record) or "kept_confirmed"
    return await _update(db, rtype, record, new, settings)


async def apply(
    db: AsyncSession,
    rtype: RecordType,
    row: Any,
    email: str,
    record: Record | None,
    *,
    settings: RecordsSettings,
    now: datetime,
    source: str,
) -> tuple[str, list[str]]:
    """``(outcome, dropped)`` for one row; ``record`` holds ``email`` (trash
    included) or is ``None``."""
    new = _Values(rtype, row)
    for attempt in range(2):
        try:
            outcome = await _decide(db, rtype, row, email, record, new, settings, now, source)
            return outcome, new.dropped
        except (Conflict, NoResultFound):
            if attempt:
                break
            await _settle(db, rtype)
            record = await subscribe.find(db, rtype, email)
    return "invalid", new.dropped
