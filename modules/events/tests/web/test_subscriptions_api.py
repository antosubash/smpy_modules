"""``/api/events/.../subscriptions``: who may, existence hiding, secrecy, CSRF, and its refusals."""

from __future__ import annotations

import uuid

import pytest
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.calendars import BASE, MANAGER, OWNER, OWNER_P, VIEWER, E, V
from tests.support.subscriptions_http import SUBS, URL, add, app_client, calendar, row, stub_launch

STRANGER = as_user("z", V, E)


@pytest.fixture(autouse=True)
def _no_launch(monkeypatch):
    return stub_launch(monkeypatch)


@pytest.fixture
async def http():
    async with app_client() as client:
        yield client


@pytest.fixture
async def http_internal():
    """A host with the intranet switch on: a manager's flag counts and is shown."""
    async with app_client(allow_private_subscription_urls=True) as client:
        yield client


@pytest.mark.parametrize(
    ("who", "visibility", "status"),
    [
        (OWNER, "private", 201),  # the owner
        (MANAGER, "private", 201),  # events.manage sees and owns everything
        (STRANGER, "private", 404),  # cannot see the calendar
        (VIEWER, "internal", 403),  # sees it, may not subscribe
        (STRANGER, "internal", 403),
        ({}, "private", 401),
    ],
)
async def test_rights_matrix(http, who, visibility, status):
    cid = await calendar(http, visibility=visibility)
    got = await add(http, cid, who)
    assert got.status_code == status, got.text
    if status == 403:
        assert got.json()["code"] == "forbidden"
    if status == 404:
        assert got.json() == (await add(http, str(uuid.uuid4()), who)).json()
    listed = await http.get(f"{BASE}/{cid}/subscriptions", headers=who)
    assert listed.status_code == (200 if status == 201 else status)


async def test_existence_is_hidden_on_every_route(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    gone = uuid.uuid4()
    for method, path, body in (
        ("patch", "", {"label": "x"}),
        ("post", "/refresh", None),
        ("post", "/pause", None),
        ("post", "/resume", None),
        ("delete", "", None),
    ):
        want = await getattr(http, method)(
            f"{SUBS}/{gone}{path}", headers=STRANGER, **({"json": body} if body else {})
        )
        got = await getattr(http, method)(
            f"{SUBS}/{sid}{path}", headers=STRANGER, **({"json": body} if body else {})
        )
        assert (
            (got.status_code, got.json()) == (want.status_code, want.json()) == (404, want.json())
        )
    # a deleted one answers like one that never was
    assert (await http.delete(f"{SUBS}/{sid}", headers=OWNER)).status_code == 204
    again = await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)
    assert (again.status_code, again.json()) == (
        404,
        (await http.post(f"{SUBS}/{gone}/refresh", headers=OWNER)).json(),
    )


async def test_the_address_is_never_returned(http):
    cid = await calendar(http)
    made = await add(http, cid, OWNER)
    sid = made.json()["id"]
    texts = [made.text]
    texts.append((await http.get(f"{BASE}/{cid}/subscriptions", headers=OWNER)).text)
    for call in (
        http.patch(f"{SUBS}/{sid}", json={"label": "New"}, headers=OWNER),
        http.post(f"{SUBS}/{sid}/pause", headers=OWNER),
        http.post(f"{SUBS}/{sid}/resume", headers=OWNER),
        http.post(f"{SUBS}/{sid}/refresh", headers=OWNER),
    ):
        got = await call
        texts.append(got.text)
    texts.append((await http.get(f"{BASE}/{cid}", headers=OWNER)).text)
    for text in texts:
        for secret in ("SECRET-TOKEN-123", "SECRET2", "private/", "enc:v2", "etag", "lease"):
            assert secret not in text, secret
    assert made.json()["url_display"] == "https://feeds.example.test/…"
    assert made.status_code == 201


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("not a url", "url_invalid"),
        ("ftp://feeds.example.test/x.ics", "url_scheme"),
        ("http://feeds.example.test/x.ics", "url_scheme"),
        ("https://u:p@feeds.example.test/x.ics", "url_userinfo"),
        ("https://feeds.example.test:8443/x.ics", "url_port"),
        ("https://127.0.0.1/x.ics", "url_unreachable"),
        ("https://[::1]/x.ics", "url_unreachable"),
        ("https://169.254.169.254/latest/", "url_unreachable"),
        ("https://2130706433/", "url_invalid"),
        ("https://feeds.example.test/" + "a" * 2100, "url_invalid"),
    ],
)
async def test_save_refusals_are_mapped_and_never_echo_the_address(http, url, code):
    cid = await calendar(http)
    got = await add(http, cid, OWNER, url=url + "?SECRET-Q")
    assert got.status_code == 422, got.text
    assert got.json()["code"] == code
    assert "SECRET-Q" not in got.text and set(got.json()) == {"detail", "code"}


async def test_a_private_literal_and_an_internal_name_give_the_identical_answer(http):
    """Resolution happens only in the worker, so save-time latency and text carry nothing."""
    cid = await calendar(http)
    literal = await add(http, cid, OWNER, url="https://10.0.0.5/x.ics")
    other = await add(http, cid, OWNER, url="https://169.254.169.254/x.ics")
    assert (literal.status_code, literal.json()) == (other.status_code, other.json())
    name = await add(http, cid, OWNER, url="https://internal.example.test/x.ics")
    assert name.status_code == 201  # not resolved here: its status follows from the worker


async def test_the_site_s_own_feed_is_refused(http):
    cid = await calendar(http)
    own = f"http://test{_urls.calendar_ics_path(None, 'en')}"
    for url in (own.replace("http:", "https:"), "https://test/events/feed/SOMETOKEN.ics"):
        got = await add(http, cid, OWNER, url=url)
        assert (got.status_code, got.json()["code"]) == (422, "url_own_feed"), got.text


async def test_the_body_cannot_set_the_internal_flag_or_anything_unknown(http):
    cid = await calendar(http)
    got = await add(http, cid, OWNER, may_use_private=True)
    assert got.status_code == 422
    made = await add(http, cid, OWNER)
    assert (await row(http, made.json()["id"])).may_use_private is False
    patched = await http.patch(
        f"{SUBS}/{made.json()['id']}", json={"may_use_private": True}, headers=OWNER
    )
    assert patched.status_code == 422
    for field in ("status", "item_count", "url_enc", "etag", "lease_owner"):
        assert (await add(http, cid, OWNER, **{field: "x"})).status_code == 422


async def test_a_manager_s_subscription_carries_the_flag_and_a_non_manager_s_does_not(
    http_internal,
):
    cid = await calendar(http_internal, OWNER_P)
    mine = (await add(http_internal, cid, OWNER)).json()
    theirs = (await add(http_internal, cid, MANAGER, url="https://other.example.test/a.ics")).json()
    assert (
        mine["may_use_internal_addresses"] is False and theirs["may_use_internal_addresses"] is True
    )
    # a non-manager changing the address of a manager's subscription clears the flag...
    edited = await http_internal.patch(
        f"{SUBS}/{theirs['id']}", json={"url": "https://x.example.test/b.ics"}, headers=OWNER
    )
    assert edited.status_code == 200 and edited.json()["may_use_internal_addresses"] is False
    # ...while another edit leaves a manager's flag alone
    kept = (await add(http_internal, cid, MANAGER, url="https://third.example.test/a.ics")).json()
    renamed = await http_internal.patch(
        f"{SUBS}/{kept['id']}", json={"label": "Renamed"}, headers=OWNER
    )
    assert renamed.json()["may_use_internal_addresses"] is False  # not told to a non-manager
    assert (await row(http_internal, kept["id"])).may_use_private is True  # but kept


async def test_writes_need_csrf(csrf_client):
    from tests.support.calendars import BASE as CAL

    token = (await csrf_client.get("/token")).json()["token"]
    made = await csrf_client.post(
        CAL, json={"name": "T"}, headers={**OWNER_P, "X-CSRF-Token": token}
    )
    cid = made.json()["id"]
    got = await add(csrf_client, cid, OWNER)
    assert got.status_code == 403
    ok = await csrf_client.post(
        f"{CAL}/{cid}/subscriptions",
        json={"url": URL, "label": "x"},
        headers={**OWNER, "X-CSRF-Token": token},
    )
    assert ok.status_code == 201


async def test_only_a_manager_is_told_that_an_address_may_be_internal(http_internal):
    cid = await calendar(http_internal, OWNER_P)
    theirs = (await add(http_internal, cid, MANAGER, url="https://other.example.test/a.ics")).json()
    assert theirs["may_use_internal_addresses"] is True  # the manager who saved it sees it
    for headers in (OWNER, MANAGER):
        got = await http_internal.get(f"{BASE}/{cid}/subscriptions", headers=headers)
        flag = got.json()[0]["may_use_internal_addresses"]
        assert flag is (headers is MANAGER), headers  # the owner without manage gets false
    edited = await http_internal.patch(f"{SUBS}/{theirs['id']}", json={"label": "X"}, headers=OWNER)
    assert edited.json()["may_use_internal_addresses"] is False


async def test_a_non_manager_sees_one_generic_failure_for_an_internal_subscription(http_internal):
    from datetime import UTC, datetime

    from sm_events.models import Subscription
    from sqlalchemy import update

    cid = await calendar(http_internal, OWNER_P)
    theirs = (await add(http_internal, cid, MANAGER, url="https://other.example.test/a.ics")).json()
    async with http_internal.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(
                status="error", error_code="not_a_calendar", last_http_status=None,
                last_fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )  # fmt: skip
        await db.commit()
    for headers, code in ((MANAGER, "not_a_calendar"), (OWNER, "url_unreachable")):
        got = (await http_internal.get(f"{BASE}/{cid}/subscriptions", headers=headers)).json()[0]
        assert (got["id"], got["error_code"], got["last_http_status"]) == (theirs["id"], code, None)
