"""Recording what a tick could not send in time.

A reminder is due for a catch-up window (:data:`REMINDER_CATCHUP`); later it is stale and never
sent. When more reminders were due at once than a tick may send, the rest used to leave the
window without a trace. This records them: for starts whose window closed within the last
:data:`REMINDER_TOO_LATE_LOOKBACK`, every follower who would have been reminded (the follow
existed when the reminder was due, and the recipient may still see the event) and has no ledger
row gets a terminal ``failed`` row with code ``too_late``. A row is never mail, is unique per
``(event, occurrence, start, recipient, lead)`` like every ledger row (an existing row is never
touched) and at most :data:`REMINDER_TOO_LATE_BATCH` are written per tenant and tick.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.constants.reminders_limits import (
    REMINDER_LEADS,
    REMINDER_TOO_LATE_BATCH,
    REMINDER_TOO_LATE_LOOKBACK,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.models import EventFollow, ReminderSent
from sm_events.reminders import candidates, due, recipients
from sm_events.reminders.claim import FAILED, insert_for
from sm_events.reminders.runtime import ReminderRuntime

__all__ = ["record_too_late"]

_F, _L = EventFollow.__table__, ReminderSent.__table__


async def record_too_late(db: Any, runtime: ReminderRuntime, *, now: datetime) -> int:
    """Write the ``too_late`` rows for the bound tenant; how many were offered (a row that
    already existed counts too, it is simply left alone)."""
    tenant = bound_tenant()
    in_use = {
        lead
        for (lead,) in await db.execute(
            select(_F.c.lead_minutes).where(_F.c.tenant_id == tenant).distinct()
        )
        if lead in REMINDER_LEADS
    }
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    pending: list[candidates.Candidate] = []
    budget = REMINDER_TOO_LATE_BATCH
    for lead in sorted(in_use):
        if budget <= 0:
            break
        edge = due.start_window(now, lead)[0]
        found = await candidates.stale_candidates(
            db, now=now, lead=lead, lo=edge - REMINDER_TOO_LATE_LOOKBACK, hi=edge, cap=budget
        )
        budget -= len(found)
        for c in found:
            wanted[c.user_id].add(c.event_id)
            pending.append(c)
    if not pending:
        return 0
    allowed = await recipients.eligible(db, runtime, tenant_id=tenant, wanted=wanted)
    rows = [
        {
            "tenant_id": tenant,
            "event_id": c.event_id,
            "occurrence_key": c.occurrence_key,
            "starts_at": c.start,
            "recipient_id": c.user_id,
            "lead_minutes": c.lead,
            "state": FAILED,
            "code": constants.REMINDER_CODE_TOO_LATE,
            "claimed_at": now,
        }
        for c in pending
        if (seen := allowed.allowed.get(c.user_id)) is not None and c.event_id in seen[1]
    ]
    if not rows:
        return 0
    statement = insert_for(db)(_L).values(rows).on_conflict_do_nothing()
    await db.execute(statement)
    mark_written(db)
    return len(rows)
