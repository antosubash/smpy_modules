"""Admin actions on a website submission (#101): resend, spam and not spam."""

from __future__ import annotations

from simple_module_hosting.csrf import CSRF_HEADER
from sm_records.models import RecordType
from sqlalchemy import select

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, ROLE_VIEWER, roles, seed_record
from tests.csrf_support import _token
from tests.public_submissions_support import API, update
from tests.public_submissions_support import create as create_type
from tests.submissions_http import (
    contact_type,
    records_of,
    send,
)


def _action(key: str, uuid: str, what: str) -> str:
    return f"{API}/{key}/records/{uuid}/submission/{what}"


async def _one(site, key: str = "contact", as_: str = ADMIN) -> str:
    assert (await send(site, key)).status_code == 202
    (record,) = await records_of(site, key, as_=as_)
    return record["uuid"]


async def test_spam_moves_a_submission_to_the_trash_and_not_spam_brings_it_back(site):
    await contact_type(site)
    uuid = await _one(site)
    assert len(site.outbox.sent) == 1
    spam = await site.post(_action("contact", uuid, "spam"), headers=roles(ADMIN))
    assert spam.status_code == 200, spam.text
    assert spam.json()["is_deleted"] is True
    assert spam.json()["data"]["sm_spam"] == "manual"
    assert await records_of(site) == []

    back = await site.post(_action("contact", uuid, "not-spam"), headers=roles(ADMIN))
    assert back.status_code == 200, back.text
    assert back.json()["is_deleted"] is False
    assert back.json()["data"]["sm_spam"] is None
    from sm_records.public_submissions import mail_runner

    await mail_runner.drain()
    assert len(site.outbox.sent) == 2, "the notification a spam verdict held back is sent"


async def test_not_spam_needs_a_trashed_record(site):
    await contact_type(site)
    uuid = await _one(site)
    resp = await site.post(_action("contact", uuid, "not-spam"), headers=roles(ADMIN))
    assert (resp.status_code, resp.json()["code"]) == (409, "not_in_trash")


async def test_resend_queues_the_notification_once_a_minute(site):
    from sm_records.public_submissions import mail_runner

    await contact_type(site)
    uuid = await _one(site)
    first = await site.post(_action("contact", uuid, "resend"), headers=roles(ADMIN))
    assert (first.status_code, first.json()) == (202, {"queued": True})
    await mail_runner.drain()
    assert len(site.outbox.sent) == 2
    again = await site.post(_action("contact", uuid, "resend"), headers=roles(ADMIN))
    assert (again.status_code, again.json()["code"]) == (429, "rate_limited")
    assert "retry-after" in again.headers


async def test_resend_recovers_a_lost_mail(site):
    """The after-commit send failed: the mark stays null, *Resend* sends it."""
    from sm_records.public_submissions import mail_runner

    await contact_type(site)
    site.outbox.fail = True
    uuid = await _one(site)
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"] is None, "a failed send leaves it 'not sent'"
    site.outbox.fail = False
    resp = await site.post(_action("contact", uuid, "resend"), headers=roles(ADMIN))
    assert resp.status_code == 202, resp.text
    await mail_runner.drain()
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"]
    assert len(site.outbox.sent) == 1


async def test_resend_needs_somebody_to_notify(site):
    await contact_type(site)
    uuid = await _one(site)
    assert (
        await update(
            site,
            "contact",
            public_submissions={
                "kind": "form",
                "enabled": True,
                "public_fields": ["name", "email", "message"],
            },
        )
    ).status_code == 200
    resp = await site.post(_action("contact", uuid, "resend"), headers=roles(ADMIN))
    assert (resp.status_code, resp.json()["code"]) == (409, "no_recipients")


async def test_an_ordinary_type_is_the_wrong_kind(site):
    made = await site.post(
        API,
        json={
            "key": "plain",
            "label": "Plain",
            "fields": [{"key": "t", "type": "text", "label": "T"}],
        },
        headers=roles(ADMIN),
    )
    assert made.status_code == 201, made.text
    record = await site.post(
        f"{API}/plain/records", json={"data": {"t": "x"}}, headers=roles(ADMIN)
    )
    uuid = record.json()["uuid"]
    for what in ("resend", "spam", "not-spam"):
        resp = await site.post(_action("plain", uuid, what), headers=roles(ADMIN))
        assert (resp.status_code, resp.json()["code"]) == (409, "wrong_kind"), what


async def test_the_actions_need_records_edit_and_the_types_roles(site):
    await contact_type(site, "narrow")
    assert (await update(site, "narrow", allowed_roles=[ROLE_EDITOR])).status_code == 200
    uuid = await _one(site, "narrow", ROLE_EDITOR)
    for what in ("resend", "spam", "not-spam"):
        viewer = await site.post(_action("narrow", uuid, what), headers=roles(ROLE_VIEWER))
        assert viewer.status_code == 403, (what, viewer.text)
        other = await site.post(_action("narrow", uuid, what), headers=roles(ROLE_EDITOR_TWO))
        assert other.status_code == 403, (what, other.text)
    ok = await site.post(_action("narrow", uuid, "spam"), headers=roles(ROLE_EDITOR))
    assert ok.status_code == 200, ok.text


async def test_the_actions_need_the_csrf_token(session_client):
    token = await _token(session_client)
    headers = {**roles(ADMIN), CSRF_HEADER: token}
    made = await create_type(session_client, "contact")
    assert made.status_code == 403, "the helper sends no token"
    from tests.public_submissions_support import contact_fields, form_config

    body = {
        "key": "contact",
        "label": "C",
        "fields": contact_fields(),
        "public_submissions": form_config(),
    }
    assert (await session_client.post(API, json=body, headers=headers)).status_code == 201
    data = {"name": "A", "email": "a@b.org", "message": "m"}
    created = await session_client.post(
        f"{API}/contact/records", json={"data": data}, headers=headers
    )
    assert created.status_code == 201, created.text
    url = _action("contact", created.json()["uuid"], "spam")
    assert (await session_client.post(url, headers=roles(ADMIN))).status_code == 403
    assert (await session_client.post(url, headers=headers)).status_code == 200


async def test_a_record_that_fails_its_schema_takes_the_marks_and_cannot_cycle(site):
    """A record no longer valid under its type (a forced change) cannot take
    an ordinary write, but the server-owned marks are written directly: it is
    trashed as spam, Not spam clears the mark, and after an ordinary delete it
    cannot be "not spam" again (each cycle would mail everyone)."""
    await contact_type(site)
    async with site.db_state.session_factory() as session:
        stmt = select(RecordType).where(RecordType.key == "contact")
        rtype = (await session.execute(stmt)).scalar_one()
    record = await seed_record(site.db_state, rtype, {"email": "not-an-email"}, uuid="d" * 32)
    spam = await site.post(_action("contact", record.uuid, "spam"), headers=roles(ADMIN))
    assert spam.status_code == 200, spam.text
    assert spam.json()["is_deleted"] is True
    assert spam.json()["data"]["sm_spam"] == "manual"
    assert spam.json()["data"]["email"] == "not-an-email", "the visitor's values are untouched"
    back = await site.post(_action("contact", record.uuid, "not-spam"), headers=roles(ADMIN))
    assert back.status_code == 200, back.text
    assert back.json()["is_deleted"] is False and back.json()["data"]["sm_spam"] is None
    gone = await site.delete(f"{API}/contact/records/{record.uuid}", headers=roles(ADMIN))
    assert gone.status_code == 204
    again = await site.post(_action("contact", record.uuid, "not-spam"), headers=roles(ADMIN))
    assert (again.status_code, again.json()["code"]) == (409, "not_in_trash")


async def test_not_spam_is_only_for_a_submission_kept_as_spam(site):
    """A record a person deleted is restored with Restore, which mails nobody."""
    await contact_type(site)
    uuid = await _one(site)
    deleted = await site.delete(f"{API}/contact/records/{uuid}", headers=roles(ADMIN))
    assert deleted.status_code == 204
    resp = await site.post(_action("contact", uuid, "not-spam"), headers=roles(ADMIN))
    assert (resp.status_code, resp.json()["code"]) == (409, "not_in_trash")


async def test_a_record_trashed_under_a_racing_spam_is_a_409_not_a_500(monkeypatch):
    """A concurrent Mark as spam trashed the row: the version conflict's
    reload cannot see it, and the answer is the conflict, not a crash."""
    from types import SimpleNamespace

    import pytest
    from sm_records.public_submissions import system
    from sm_records.services.errors import Conflict
    from sqlalchemy.exc import InvalidRequestError

    async def stale(*args, **kwargs):
        raise Conflict("record changed", current=object())

    async def gone(record):
        raise InvalidRequestError("Could not refresh instance")

    monkeypatch.setattr(system.record_service, "update_record", stale)
    monkeypatch.setattr(system, "_ordinary", lambda rtype, record: {})
    db = SimpleNamespace(refresh=gone, info={})
    with pytest.raises(Conflict) as refused:
        await system.system_update(db, None, SimpleNamespace(version=1), {}, settings=None)
    assert refused.value.current is None, "no unreloadable row for the 409 body to render"
