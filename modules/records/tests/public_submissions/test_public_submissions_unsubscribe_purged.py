"""An unsubscribe that races a purge (newsletter PR 6): the row is gone by the
time ``leave`` locks it. The link still answers its one ``200`` and the admin
action answers ``404``, never a ``500`` from ``NoResultFound``."""

from __future__ import annotations

import pytest
from sm_records.public_submissions import transition
from sm_records.public_submissions.row_lock import lock_record
from sqlalchemy.exc import NoResultFound

from tests.support.newsletter_http import admin, follow, links_in, signup, subscriber


@pytest.fixture
def purged(monkeypatch):
    """Every locked reload finds its row purged."""

    async def gone(db, rtype, record):
        return await lock_record(db, rtype, type(record)(id=-1, tenant_id=record.tenant_id))

    monkeypatch.setattr(transition, "lock_record", gone)


async def _signed_up(site) -> str:
    assert (await signup(site)).status_code == 202
    return links_in(site.outbox.sent[-1])["unsubscribe"]["t"]


async def test_the_link_answers_as_for_an_unknown_subscriber(newsletter, purged):
    token = await _signed_up(newsletter)
    resp = await follow(newsletter, "unsubscribe", token)
    assert (resp.status_code, resp.json()) == (200, {"status": "unsubscribed"})


async def test_the_admin_action_answers_404(newsletter, purged):
    await _signed_up(newsletter)
    uuid = (await subscriber(newsletter))["uuid"]
    resp = await admin(newsletter, uuid, "unsubscribe")
    assert resp.status_code == 404, resp.text


async def test_a_confirm_link_on_a_purged_row_is_an_expired_link(newsletter, monkeypatch):
    """The confirm reloads without a lock; a purge since its lookup answers
    ``410 link_expired`` like a trashed row, not a ``404``."""
    token = await _confirm_token(newsletter)

    async def gone(db, record):
        raise NoResultFound()

    monkeypatch.setattr(transition, "_reload", gone)
    resp = await follow(newsletter, "confirm", token)
    assert (resp.status_code, resp.json()["code"]) == (410, "link_expired"), resp.text


async def _confirm_token(site) -> str:
    assert (await signup(site)).status_code == 202
    return links_in(site.outbox.sent[-1])["confirm"]["t"]
