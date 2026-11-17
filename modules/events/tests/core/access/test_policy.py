"""The calendar policy's truth table, as SQL and through ``calendar_rights``.

``filter`` is the authority; ``can`` may say no where ``filter`` says yes (a
share is a row), but never yes where ``filter`` says no.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_core.resources import ACTION_DELETE, ACTION_EDIT, ACTION_SHARE, ACTION_VIEW
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY, visible_calendars
from sm_events.core.access.rights import calendar_rights
from sm_events.models import Calendar
from sqlmodel import select

from tests.support.access import principal, seed_calendars, share

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"

# name: (user id, permissions, view, edit, delete/share, write_events, publish)
TABLE = {
    "M": ("m", (M,), "PIU", "PIU", "PIU", "PIU", ""),
    "M+P": ("m", (M, P), "PIU", "PIU", "PIU", "PIU", "PIU"),
    "O": ("o", (V,), "PIU", "PIU", "PIU", "PIU", ""),
    "O+P": ("o", (V, P), "PIU", "PIU", "PIU", "PIU", "PIU"),
    "O-": ("o", (), "U", "", "", "", ""),
    "SV": ("sv", (V, E), "PIU", "", "", "IU", ""),
    "SV-": ("sv", (), "U", "", "", "", ""),
    "SE": ("se", (V,), "PIU", "PIU", "", "PIU", ""),
    "E": ("e", (V, E), "IU", "", "", "IU", ""),
    "E+P": ("e", (V, E, P), "IU", "", "", "IU", "IU"),
    "V": ("v", (V,), "IU", "", "", "", ""),
    "N": ("n", (), "U", "", "", "", ""),
    "A": (None, (), "U", "", "", "", ""),
}
ACTIONS = {
    "view": ACTION_VIEW,
    "edit": ACTION_EDIT,
    "delete": ACTION_DELETE,
    "share": ACTION_SHARE,
    "write_events": ACTION_WRITE_EVENTS,
}


def _letter(cal: Calendar) -> str:
    return {"private": "P", "internal": "I", "public": "U"}[cal.slug]


@pytest.mark.parametrize("name", list(TABLE))
async def test_truth_table(db, name):
    uid, perms, view, edit, own, write, publish = TABLE[name]
    who = principal(uid, *perms)
    cals = await seed_calendars(db)
    expected = {
        ACTION_VIEW: set(view),
        ACTION_EDIT: set(edit),
        ACTION_DELETE: set(own),
        ACTION_SHARE: set(own),
        ACTION_WRITE_EVENTS: set(write),
    }
    for action, want in expected.items():
        rows = (await db.execute(POLICY.filter(who, action, select(Calendar)))).scalars().all()
        assert {_letter(r) for r in rows} == want, (name, action)
        for letter, cal in cals.items():
            if POLICY.can(who, action, cal):
                assert letter in want, (name, action, letter, "can() says yes, filter no")
    for letter, cal in cals.items():
        rights = await calendar_rights(db, who, cal)
        assert rights.view is (letter in view), (name, letter)
        assert rights.edit_calendar is (letter in edit), (name, letter)
        assert rights.own is (letter in own), (name, letter)
        assert rights.write_events is (letter in write), (name, letter)
        assert rights.see_drafts is rights.write_events
        assert rights.publish is (letter in publish), (name, letter)


async def test_expired_share_grants_nothing(db):
    cals = await seed_calendars(db)
    past = datetime.now(UTC) - timedelta(days=1)
    for cal in cals.values():
        db.add(share(cal, "sx", "edit", expires_at=past))
    await db.flush()
    who = principal("sx", V)
    for action, want in ((ACTION_VIEW, "IU"), (ACTION_EDIT, ""), (ACTION_WRITE_EVENTS, "")):
        rows = (await db.execute(POLICY.filter(who, action, select(Calendar)))).scalars().all()
        assert {_letter(r) for r in rows} == set(want), action


async def test_share_never_grants_delete(db):
    cals = await seed_calendars(db)
    who = principal("se", V)
    assert not POLICY.can(who, ACTION_DELETE, cals["P"])
    rows = (await db.execute(POLICY.filter(who, ACTION_DELETE, select(Calendar)))).scalars().all()
    assert rows == []


async def test_trashed_calendar_invisible(db):
    cals = await seed_calendars(db)
    cals["I"].is_deleted = True
    cals["I"].deleted_at = datetime.now(UTC)
    await db.flush()
    for who in (principal("v", V), principal("m", M)):
        rows = (await db.execute(visible_calendars(who))).scalars().all()
        assert "I" not in {_letter(r) for r in rows}


async def test_unknown_action_grants_nothing(db):
    await seed_calendars(db)
    rows = (
        (await db.execute(POLICY.filter(principal("o", V), "frobnicate", select(Calendar))))
        .scalars()
        .all()
    )
    assert rows == []
