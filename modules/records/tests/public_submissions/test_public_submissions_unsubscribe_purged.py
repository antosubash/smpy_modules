"""An unsubscribe that races a purge (newsletter PR 6): the row is gone by the
time ``leave`` locks it. The link still answers its one ``200`` and the admin
action answers ``404``, never a ``500`` from ``NoResultFound``."""

from __future__ import annotations

import pytest
from sm_records.public_submissions import transition
from sm_records.public_submissions.row_lock import lock_record

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
