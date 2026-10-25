"""The direct mark write on a record that fails its schema (#101) is a guarded
compare-and-set: an admin's repair saved meanwhile is never overwritten."""

from __future__ import annotations

from sm_records import events
from sm_records.public_submissions import system
from sm_records.services.records import get_record
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles, seed_record
from tests.public_submissions_support import API
from tests.submissions_http import contact_type

REPAIRED = {"name": "Ada", "email": "ada@example.org", "message": "fixed by an admin"}


async def _stale_then_repaired(site) -> tuple[object, object, object, str]:
    """A misfit record loaded by a worker's session, then repaired by an admin."""
    await contact_type(site)
    session = site.db_state.session_factory()
    rtype = await get_type(session, "contact")
    seeded = await seed_record(site.db_state, rtype, {"email": "not-an-email"}, uuid="e" * 32)
    record = await get_record(session, rtype, seeded.uuid)
    repair = await site.put(
        f"{API}/contact/records/{seeded.uuid}",
        json={"expected_version": record.version, "data": REPAIRED},
        headers=roles(ADMIN),
    )
    assert repair.status_code == 200, repair.text
    return session, rtype, record, seeded.uuid


async def _stored(site, uuid: str) -> dict:
    resp = await site.get(f"{API}/contact/records/{uuid}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_repair_saved_while_a_mark_is_pending_is_kept(site):
    session, rtype, stale, uuid = await _stale_then_repaired(site)
    try:
        await system.try_system_update(
            session, rtype, stale, {"sm_spam": "manual"}, settings=RecordsSettings()
        )
        await events.commit(session)
    finally:
        await session.close()
    stored = await _stored(site, uuid)
    assert {key: stored["data"][key] for key in REPAIRED} == REPAIRED, "the repair survived"
    assert stored["data"]["sm_spam"] == "manual", "and the mark landed"
    assert stored["version"] == 3


async def test_a_lost_race_retries_from_the_current_row(site, monkeypatch):
    """The compare-and-set lost (the row moved): the retry reloads it, finds it
    repaired, and takes the ordinary write."""
    session, rtype, stale, uuid = await _stale_then_repaired(site)
    real = system._merge_marks
    calls: list[int] = []

    async def lost_once(*args, **kwargs):
        calls.append(1)
        return False if len(calls) == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(system, "_merge_marks", lost_once)
    try:
        await system.try_system_update(
            session, rtype, stale, {"sm_spam": "manual"}, settings=RecordsSettings()
        )
        await events.commit(session)
    finally:
        await session.close()
    assert calls == [1], "the second attempt took the ordinary write"
    stored = await _stored(site, uuid)
    assert {key: stored["data"][key] for key in REPAIRED} == REPAIRED
    assert stored["data"]["sm_spam"] == "manual"
