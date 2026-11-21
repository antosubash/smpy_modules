"""``summaries``: the public facts about many occurrences at once, for "my registrations".

One answer per reference: the :class:`RegistrationEvent` or ``None``, and ``None`` is exactly what
``describe`` would call ``unavailable`` (not public, not this provider's, not an occurrence). The
cost is a handful of statements whatever the number of references (at most
``SUMMARIES_MAX``), never one per reference.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.access.public import public_events
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, OccurrenceOverride
from sm_events.registration import args
from sm_events.registration.availability import RegistrationEvent, choose_text, make_event
from sm_events.registration.occurrence import original_start_of, resolve_key

__all__ = ["summaries"]


def _refs(refs: Any) -> list[tuple[uuid.UUID, str]]:
    if isinstance(refs, str | bytes) or not isinstance(refs, Sequence):
        raise ValueError("refs must be a sequence of (event_id, occurrence_key)")
    if len(refs) > constants.SUMMARIES_MAX:
        raise ValueError(f"at most {constants.SUMMARIES_MAX} refs")
    out: list[tuple[uuid.UUID, str]] = []
    for ref in refs:
        if not isinstance(ref, tuple | list) or len(ref) != 2:
            raise ValueError("a ref is (event_id, occurrence_key)")
        out.append((args.event_id(ref[0]), args.occurrence_key(ref[1])))
    return list(dict.fromkeys(out))


async def summaries(
    db: Any, *, tenant_id: str, provider: str, refs: Sequence[tuple[uuid.UUID, str]], locale: str
) -> dict[tuple[uuid.UUID, str], RegistrationEvent | None]:
    wanted = _refs(refs)
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    lang = args.text(locale, "locale", maximum=constants.LOCALE_MAX)
    found: dict[tuple[uuid.UUID, str], RegistrationEvent | None] = dict.fromkeys(wanted)
    with tenant_scope(tenant_id):
        if not wanted:
            return found
        ids = sorted({event_id for event_id, _ in wanted})
        stmt = public_events().where(
            Event.id.in_(ids),  # type: ignore[attr-defined]
            Event.registration_mode == constants.REGISTRATION_MODE_BUILTIN,
            Event.registration_provider == who,
        )
        events = {e.id: e for e in (await db.execute(stmt)).scalars()}
        if not events:
            return found
        originals = {
            o
            for event_id, key in wanted
            if (event := events.get(event_id)) is not None and event.rrule is not None
            if (o := original_start_of(event, key)) is not None
        }
        changes: dict[uuid.UUID, list[OccurrenceOverride]] = {}
        if originals:
            rows = await db.execute(
                select(OccurrenceOverride).where(
                    OccurrenceOverride.event_id.in_(list(events)),  # type: ignore[attr-defined]
                    OccurrenceOverride.original_start.in_(originals),  # type: ignore[attr-defined]
                )
            )
            for row in rows.scalars():
                changes.setdefault(row.event_id, []).append(row)
        texts = await texts_of(db, list(events))
        for event_id, key in wanted:
            event = events.get(event_id)
            if event is None:
                continue
            occurrence = resolve_key(event, changes.get(event_id, []), key)
            if occurrence is not None:
                found[(event_id, key)] = make_event(
                    event, occurrence, choose_text(texts[event_id], lang), lang
                )
    return found
