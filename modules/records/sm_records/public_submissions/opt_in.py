"""Confirming and leaving a newsletter list (#101, design §7.2 and §10).

**Confirm** (the link's ``POST``): a ``pending`` subscriber whose nonce the
link was minted for becomes ``confirmed`` (``sm_confirmed_at``); one already
confirmed answers ``already_confirmed``, so a second click — or a mail
scanner that did run the page's script — changes nothing. Anything else is
``410 link_expired``: an expired link, one for an earlier subscription (the
nonce moved on), an unsubscribed or deleted subscriber, a list switched off.

**Unsubscribe** (the link's ``POST``, or an admin's action): the record stays,
as a **suppression record** — ``sm_email``, ``sm_status = "unsubscribed"`` and
``sm_unsubscribed_at`` — so a re-import cannot resubscribe the address
silently. The consent proof and every ordinary value are cleared (a required
ordinary field keeps its value: clearing it would make the record unsaveable),
and ``sm_nonce`` rotates, which kills every link minted before. Idempotent.
The link route answers the same ``200`` whatever happened here, so it is no
oracle.

Both are compare-and-set transitions (:mod:`.transition`): each attempt
reloads the row and re-checks the nonce and the source status, so a change
decided from a row that has since moved is decided again, never replayed.
They are system writes (``events.muted``), announced once, by the request
that wrote, as :class:`~sm_records.contracts.events.SubscriptionChanged`. A
record that no longer satisfies its schema still takes them — ordinary values
cleared in the same step — so an unsubscribe is never refused because an
admin forced a schema change.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.models import Record, RecordType
from sm_records.public_submissions import links
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.subscribe import CONFIRMED, PENDING, UNSUBSCRIBED, changed
from sm_records.public_submissions.transition import Change, transition
from sm_records.services import records as record_service
from sm_records.services._common import utcnow
from sm_records.services._payload import field_defs
from sm_records.services.errors import NotFound
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

__all__ = ["confirm", "leave", "unsubscribe"]

_EXPIRED = "this link has expired or is no longer valid; sign up again"


async def _subscriber(db: AsyncSession, link: links.Link) -> tuple[RecordType, Record] | None:
    """The live subscriber the link names, in the tenant it names (bound by
    the caller). Explicit ``tenant_id`` on both lookups (``get_type``,
    ``_by_uuid``)."""
    try:
        rtype = await get_type(db, link.type_key)
        if (rtype.public_submissions or {}).get("kind") != KIND_SUBSCRIPTION:
            return None
        return rtype, await record_service.get_record(db, rtype, link.uuid)
    except NotFound:
        return None


def _expired() -> SubmissionRefused:
    return SubmissionRefused("link_expired", _EXPIRED)


async def confirm(
    db: AsyncSession, secret: str, link: links.Link, settings: RecordsSettings
) -> str:
    """``"confirmed"`` or ``"already_confirmed"``; else ``410 link_expired``.

    Decided from the row as it is when the write lands (:mod:`.transition`):
    an unsubscribe that rotated the nonce in between makes this link expired,
    and of two confirms only the one that wrote announces it."""
    found = await _subscriber(db, link)
    if found is None or not (found[0].public_submissions or {}).get("enabled"):
        raise _expired()
    rtype, record = found

    def derive(row: Record) -> Change | None:
        data = row.data or {}
        if row.is_deleted or not links.matches(secret, link, data.get("sm_nonce")):
            raise _expired()
        if data.get("sm_status") == CONFIRMED:
            return None
        if data.get("sm_status") != PENDING:
            raise _expired()
        return {"sm_status": CONFIRMED, "sm_confirmed_at": utcnow()}, None

    outcome = await transition(db, rtype, record, derive, settings=settings)
    if not outcome.wrote:
        return "already_confirmed"
    events.emit(db, changed(rtype, outcome.record, PENDING, CONFIRMED))
    return "confirmed"


def _cleared(rtype: RecordType, record: Record) -> dict[str, Any]:
    """The ordinary values an unsubscribed record keeps: none, except a
    required one, which the schema would refuse to clear."""
    data = record.data or {}
    return {
        entry.key: data.get(entry.key) if entry.required else None
        for entry in field_defs(rtype)
        if not entry.system and entry.key in data
    }


async def leave(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    settings: RecordsSettings,
    *,
    still: Callable[[Record], bool] | None = None,
) -> Record:
    """Unsubscribe ``record``: the suppression record, consent and ordinary
    values cleared, the nonce rotated. Nothing to do for one already
    unsubscribed — or, with ``still``, for a row it no longer holds for (the
    link's nonce moved on)."""

    def derive(row: Record) -> Change | None:
        if (row.data or {}).get("sm_status") == UNSUBSCRIBED or (still and not still(row)):
            return None
        values = {
            "sm_status": UNSUBSCRIBED,
            "sm_unsubscribed_at": utcnow(),
            "sm_nonce": secrets.token_hex(16),
            "sm_consent_text": None,
            "sm_consent_at": None,
            "sm_consent_ip_hash": None,
            "sm_confirmed_at": None,
        }
        return values, _cleared(rtype, row)

    outcome = await transition(db, rtype, record, derive, settings=settings)
    if outcome.wrote:
        before = outcome.before.get("sm_status")
        events.emit(db, changed(rtype, outcome.record, before, UNSUBSCRIBED))
    return outcome.record


async def unsubscribe(
    db: AsyncSession, secret: str, link: links.Link, settings: RecordsSettings
) -> None:
    """The link's unsubscribe. Silent whatever the link names: the caller
    answers the same ``200`` either way."""
    found = await _subscriber(db, link)
    if found is None:
        return
    rtype, record = found

    def holds(row: Record) -> bool:
        return not row.is_deleted and links.matches(secret, link, (row.data or {}).get("sm_nonce"))

    await leave(db, rtype, record, settings, still=holds)
