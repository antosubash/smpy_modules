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

Both are system writes (``events.muted``: not a content edit) announced as
:class:`~sm_records.contracts.events.SubscriptionChanged`. A record that no
longer satisfies its schema still takes them, through the guarded
compare-and-set of :func:`~.system.try_system_update` — an unsubscribe in
particular must never be refused because an admin forced a schema change.
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.models import Record, RecordType
from sm_records.public_submissions import links
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.subscribe import CONFIRMED, PENDING, UNSUBSCRIBED, changed
from sm_records.public_submissions.system import try_system_update
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


async def confirm(
    db: AsyncSession, secret: str, link: links.Link, settings: RecordsSettings
) -> str:
    """``"confirmed"`` or ``"already_confirmed"``; else ``410 link_expired``."""
    found = await _subscriber(db, link)
    if found is None:
        raise SubmissionRefused("link_expired", _EXPIRED)
    rtype, record = found
    data = record.data or {}
    if not (rtype.public_submissions or {}).get("enabled") or not links.matches(
        secret, link, data.get("sm_nonce")
    ):
        raise SubmissionRefused("link_expired", _EXPIRED)
    status = data.get("sm_status")
    if status == CONFIRMED:
        return "already_confirmed"
    if status != PENDING:
        raise SubmissionRefused("link_expired", _EXPIRED)
    values = {"sm_status": CONFIRMED, "sm_confirmed_at": utcnow()}
    record = await try_system_update(db, rtype, record, values, settings=settings)
    events.emit(db, changed(rtype, record, PENDING, CONFIRMED))
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
    db: AsyncSession, rtype: RecordType, record: Record, settings: RecordsSettings
) -> Record:
    """Unsubscribe ``record``: the suppression record, consent cleared, the
    nonce rotated. Nothing to do for one already unsubscribed."""
    before = (record.data or {}).get("sm_status")
    if before == UNSUBSCRIBED:
        return record
    values = {
        "sm_status": UNSUBSCRIBED,
        "sm_unsubscribed_at": utcnow(),
        "sm_nonce": secrets.token_hex(16),
        "sm_consent_text": None,
        "sm_consent_at": None,
        "sm_consent_ip_hash": None,
        "sm_confirmed_at": None,
    }
    record = await try_system_update(
        db, rtype, record, values, settings=settings, data=_cleared(rtype, record)
    )
    events.emit(db, changed(rtype, record, before, UNSUBSCRIBED))
    return record


async def unsubscribe(
    db: AsyncSession, secret: str, link: links.Link, settings: RecordsSettings
) -> None:
    """The link's unsubscribe. Silent whatever the link names: the caller
    answers the same ``200`` either way."""
    found = await _subscriber(db, link)
    if found is None:
        return
    rtype, record = found
    if links.matches(secret, link, (record.data or {}).get("sm_nonce")):
        await leave(db, rtype, record, settings)
