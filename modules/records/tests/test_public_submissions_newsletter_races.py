"""A subscriber's status change is a compare-and-set (#101, review of #251).

A confirm decided from a ``pending`` row must not land on a record that an
unsubscribe rotated in between, and of two confirms only one announces it.
The interleaving is forced at the write: just before the confirm's
``update_record`` the row is moved the way the competing request's commit
would move it (status, nonce, version), so the confirm's version check fails
and it has to decide again from the row as it now is. Postgres also runs two
real confirms at once. Plus the purge of a subscriber's delivery claims and
double opt-in off for an address that left.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_records.contracts.events import SubscriptionChanged
from sm_records.models import SubmissionDelivery, tables_for
from sm_records.public_submissions import transition as transition_module
from sm_records.public_submissions.attempts import MARKERS
from sm_records.tenancy import tenant_scope
from sqlalchemy import select, update

from tests.app_harness import ADMIN, roles
from tests.newsletter_http import (
    LIST,
    STORED,
    follow,
    links_in,
    newsletter_type,
    signup,
    subscriber,
)
from tests.pg_support import USING_POSTGRES


def _events(site) -> list:
    seen: list = []

    async def note(event):
        seen.append(event)

    site.app.state.sm.event_bus.subscribe(SubscriptionChanged, note)
    return seen


def _move_first_write(monkeypatch, **data_changes) -> None:
    """Before the first status write lands, move the row as a competing
    commit would: new data values and a bumped version."""
    real = transition_module.record_service.update_record
    moved: list[bool] = []

    async def racing(db, rtype, record, **kw):
        if not moved:
            moved.append(True)
            cls = tables_for(rtype).record
            await db.execute(
                update(cls)
                .where(cls.id == record.id, cls.tenant_id == record.tenant_id)
                .values(data={**record.data, **data_changes}, version=record.version + 1)
                .execution_options(synchronize_session=False)
            )
        return await real(db, rtype, record, **kw)

    monkeypatch.setattr(transition_module.record_service, "update_record", racing)


async def test_an_unsubscribe_in_between_wins_over_a_confirm(newsletter, monkeypatch):
    await signup(newsletter)
    confirm = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    seen = _events(newsletter)
    _move_first_write(monkeypatch, sm_status="unsubscribed", sm_nonce="f" * 32)
    resp = await follow(newsletter, "confirm", confirm)
    assert (resp.status_code, resp.json()["code"]) == (410, "link_expired")
    # The simulated competitor shares this request's transaction, so the 410's
    # rollback takes it too; what matters is that nothing confirmed it.
    assert (await subscriber(newsletter))["data"]["sm_status"] != "confirmed"
    assert seen == []


async def test_of_two_confirms_only_one_announces(newsletter, monkeypatch):
    await signup(newsletter)
    confirm = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    seen = _events(newsletter)
    _move_first_write(monkeypatch, sm_status="confirmed")
    resp = await follow(newsletter, "confirm", confirm)
    assert resp.json() == {"status": "already_confirmed"}
    assert seen == [], "the confirm that lost wrote nothing and announced nothing"


@pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")
async def test_two_confirms_at_once_write_and_announce_once(newsletter):
    await signup(newsletter)
    confirm = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    seen = _events(newsletter)
    answers = await asyncio.gather(
        follow(newsletter, "confirm", confirm), follow(newsletter, "confirm", confirm)
    )
    assert sorted(r.json()["status"] for r in answers) == ["already_confirmed", "confirmed"]
    assert [(e.status_before, e.status_after) for e in seen] == [("pending", "confirmed")]


async def test_an_unsubscribe_link_whose_nonce_moved_in_between_does_nothing(
    newsletter, monkeypatch
):
    await signup(newsletter)
    unsubscribe = links_in(newsletter.outbox.sent[0])["unsubscribe"]["t"]
    _move_first_write(monkeypatch, sm_nonce="e" * 32)  # a re-signup rotated it
    resp = await follow(newsletter, "unsubscribe", unsubscribe)
    assert resp.json() == {"status": "unsubscribed"}, "the same answer"
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending"


async def test_without_double_opt_in_an_address_that_left_must_confirm_again(site):
    consent = {"required": True, "text": {"en": "Yes."}}
    await newsletter_type(site, double_opt_in=False, consent=consent)
    assert (await signup(site, consent=True)).status_code == 202
    assert (await subscriber(site))["data"]["sm_status"] == "confirmed", "new: at once"
    assert site.outbox.sent == []
    uuid = (await subscriber(site))["uuid"]
    path = f"/api/records/types/{LIST}/records/{uuid}/submission/unsubscribe"
    assert (await site.post(path, headers=roles(ADMIN))).status_code == 200
    again = await signup(site, consent=True)
    assert again.status_code == 202
    data = (await subscriber(site))["data"]
    assert data["sm_status"] == "pending" and data["sm_confirmed_at"] is None
    (message,) = site.outbox.sent
    assert message.to == STORED, "back on the list only through their own confirmation"
    await site.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    await signup(site, consent=True)
    assert (await subscriber(site))["data"]["sm_status"] == "pending", "trashed: the same"


async def _deliveries(site) -> list:
    async with site.db_state.session_factory() as session:
        with tenant_scope("default"):
            stmt = select(SubmissionDelivery).where(SubmissionDelivery.tenant_id == "default")
            return list((await session.execute(stmt)).scalars())


async def test_a_purge_leaves_no_trace_of_the_address_in_the_claims(newsletter):
    await signup(newsletter)
    rows = await _deliveries(newsletter)
    # The recipient's claim, beside the attempt's manifest and completion rows.
    (claim,) = [row for row in rows if row.recipient not in MARKERS]
    assert sorted(row.recipient for row in rows if row.recipient in MARKERS) == sorted(MARKERS)
    assert claim.recipient.startswith("h:") and STORED not in claim.recipient
    uuid = (await subscriber(newsletter))["uuid"]
    base = f"/api/records/types/{LIST}/records/{uuid}"
    assert (await newsletter.delete(base, headers=roles(ADMIN))).status_code in (200, 204)
    purged = await newsletter.delete(f"{base}/purge", headers=roles(ADMIN))
    assert purged.status_code == 204, purged.text
    assert await _deliveries(newsletter) == []


async def test_deleting_the_list_forgets_its_claims(newsletter):
    await signup(newsletter)
    assert await _deliveries(newsletter)
    resp = await newsletter.delete(
        f"/api/records/types/{LIST}?confirm_record_count=1", headers=roles(ADMIN)
    )
    assert resp.status_code == 204, resp.text
    assert await _deliveries(newsletter) == []


async def test_a_restore_that_lost_a_race_does_not_reset_a_confirmation(newsletter, monkeypatch):
    """The restore forces one write; when that write loses to a confirm, the
    retry decides from the confirmed row and leaves it confirmed."""
    await signup(newsletter)
    uuid = (await subscriber(newsletter))["uuid"]
    await newsletter.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    _move_first_write(monkeypatch, sm_status="confirmed")
    assert (await signup(newsletter)).status_code == 202
    assert (await subscriber(newsletter))["data"]["sm_status"] == "confirmed"


async def test_the_admin_resend_limit_says_when_it_frees_up(newsletter):
    await signup(newsletter)
    uuid = (await subscriber(newsletter))["uuid"]
    path = f"/api/records/types/{LIST}/records/{uuid}/submission/resend"
    answers = [await newsletter.post(path, headers=roles(ADMIN)) for _ in range(3)]
    assert [a.status_code for a in answers] == [202, 202, 429]
    wait = int(answers[-1].headers["retry-after"])
    assert 0 < wait <= 86400 and wait != 3600
