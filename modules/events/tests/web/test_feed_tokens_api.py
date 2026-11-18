"""The private feed link API: create once, list without secrets, revoke."""

from __future__ import annotations

import pytest
from sm_events.core import constants
from sm_events.feeds.tokens.codec import hash_token
from sm_events.web.endpoints import feed_tokens_api  # noqa: F401 - the module exists

from tests.support.access import seed_calendars
from tests.support.app import Directory, as_user
from tests.support.tokens import ROLES, USERS, install_directory, install_members

V, M = "events.view", "events.manage"
BASE = "/api/events/calendars"
SV, SE, MGR, OWN = (as_user("sv", V), as_user("se", V), as_user("m", V, M), as_user("o", V))


async def _calendars(client, tenant: str | None = None) -> dict:
    from sm_events.core.tenancy import tenant_scope

    with tenant_scope(tenant or "default"):
        async with client.db_state.session_factory() as db:
            cals = await seed_calendars(db)
            await db.commit()
    return cals


@pytest.fixture
async def world(client):
    install_directory(client.app)
    cals = await _calendars(client)
    return client, cals


def url(cal, suffix="feed-tokens") -> str:
    return f"{BASE}/{cal.id}/{suffix}"


async def _create(client, cal, headers=SV, **body):
    body.setdefault("label", "Phone")
    return await client.post(url(cal), json=body, headers=headers)


async def test_token_shown_once(world):
    client, cals = world
    made = await _create(client, cals["P"])
    assert made.status_code == 201, made.text
    body = made.json()
    token = body["url"].rsplit("/", 1)[1].removesuffix(".ics")
    assert body["url"] == f"http://test/events/feed/{token}.ics"
    assert body["webcal_url"] == f"webcal://test/events/feed/{token}.ics"
    assert token.startswith("evf_") and body["mine"] is True and body["label"] == "Phone"
    digest = hash_token(token)

    def clean(raw: bytes) -> None:
        assert token.encode() not in raw and digest.encode() not in raw
        assert b"token_hash" not in raw

    listed = await client.get(url(cals["P"]), headers=SV)
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert set(listed.json()[0]) == {
        "id", "label", "locale", "created_at", "last_used_at", "user_id", "user_name", "mine",
    }  # fmt: skip
    clean(listed.content)
    deleted = await client.delete(
        f"{BASE.removesuffix('/calendars')}/feed-tokens/{body['id']}", headers=SV
    )
    assert deleted.status_code == 204
    clean(deleted.content)
    assert (await client.get(url(cals["P"]), headers=SV)).json() == []


async def test_create_headers(world):
    client, cals = world
    made = await _create(client, cals["P"])
    assert made.headers["cache-control"] == "no-store"
    assert made.headers["referrer-policy"] == "no-referrer"


async def test_invisible_calendar_404_everywhere(world):
    client, cals = world
    missing = "00000000-0000-0000-0000-000000000000"
    for headers in (as_user("v", V), as_user("a"), {}):
        for method in ("get", "post"):
            got = await getattr(client, method)(
                url(cals["P"]),
                headers=headers,
                **({"json": {"label": "x"}} if method == "post" else {}),
            )
            assert got.status_code in (404, 401, 403), (headers, method, got.status_code)
    for method in ("get", "post"):
        got = await getattr(client, method)(
            f"{BASE}/{missing}/feed-tokens",
            headers=SV,
            **({"json": {"label": "x"}} if method == "post" else {}),
        )
        same = await getattr(client, method)(
            url(cals["P"]),
            headers=as_user("v", V),
            **({"json": {"label": "x"}} if method == "post" else {}),
        )
        assert (got.status_code, got.json()) == (404, {"detail": "Not found", "code": "not_found"})
        assert (same.status_code, same.json()) == (got.status_code, got.json())  # a hidden one too


async def test_all_needs_manage(world):
    client, cals = world
    await _create(client, cals["P"], label="mine")
    await _create(client, cals["P"], headers=SE, label="theirs")
    assert (await client.get(url(cals["P"]), params={"all": "true"}, headers=SV)).status_code == 403
    own = await client.get(url(cals["P"]), headers=SV)
    assert [t["label"] for t in own.json()] == ["mine"]
    everyone = await client.get(url(cals["P"]), params={"all": "true"}, headers=MGR)
    assert {t["label"] for t in everyone.json()} == {"mine", "theirs"}
    assert {t["mine"] for t in everyone.json()} == {False}  # the manager owns neither


async def test_revoke_rules(world):
    client, cals = world
    mine = (await _create(client, cals["P"])).json()["id"]
    theirs = (await _create(client, cals["P"], headers=SE)).json()["id"]
    base = f"{BASE.removesuffix('/calendars')}/feed-tokens"
    assert (await client.delete(f"{base}/{theirs}", headers=SV)).status_code == 404
    missing = await client.delete(f"{base}/00000000-0000-0000-0000-000000000000", headers=SV)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert (await client.delete(f"{base}/{mine}", headers=SV)).status_code == 204
    assert (await client.delete(f"{base}/{theirs}", headers=MGR)).status_code == 204  # a manager


async def test_user_name_rule(client):
    install_directory(client.app)
    directory = client.app.state.user_directory
    directory.users["sv"] = ("sv@example.com", "sv@example.com", True)  # a label that is an address
    directory.users["se"] = ("se@example.com", "Sara Editor", True)
    cals = await _calendars(client)
    await _create(client, cals["P"])
    await _create(client, cals["P"], headers=SE)
    got = await client.get(url(cals["P"]), params={"all": "true"}, headers=MGR)
    names = {t["user_id"]: t["user_name"] for t in got.json()}
    assert names == {"sv": None, "se": "Sara Editor"}


async def test_error_envelopes(world):
    client, cals = world
    for n in range(constants.FEED_TOKENS_PER_USER_CALENDAR):
        assert (await _create(client, cals["P"], label=f"d{n}")).status_code == 201
    limit = await _create(client, cals["P"])
    assert (limit.status_code, limit.json()) == (
        409,
        {"detail": constants.TOKEN_LIMIT_DETAIL, "code": "token_limit"},
    )
    client.app.state.user_directory = Directory(dict(USERS), {**ROLES, "se": None})
    unavailable = await _create(client, cals["P"], headers=SE)
    assert (unavailable.status_code, unavailable.json()["code"]) == (
        503,
        "private_feeds_unavailable",
    )
    assert set(unavailable.json()) == {"detail", "code"}
    for bad in ({"label": ""}, {"label": "a\nb"}, {"label": "x" * 101}, {"label": " "}, {}):
        got = (
            await _create(client, cals["I"], headers=OWN, **bad)
            if bad
            else await client.post(url(cals["I"]), json={}, headers=OWN)
        )
        assert got.status_code == 422, bad
        assert isinstance(got.json()["detail"], list)  # FastAPI's own shape
    assert (await _create(client, cals["I"], headers=OWN, locale="fr")).json()[
        "code"
    ] == "unknown_locale"


async def test_writes_need_csrf(csrf_client):
    install_directory(csrf_client.app)
    cals = await _calendars(csrf_client)
    refused = await csrf_client.post(url(cals["P"]), json={"label": "x"}, headers=SV)
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    token = (await csrf_client.get("/token")).json()["token"]
    made = await csrf_client.post(
        url(cals["P"]), json={"label": "x"}, headers={**SV, "X-CSRF-Token": token}
    )
    assert made.status_code == 201
    base = f"{BASE.removesuffix('/calendars')}/feed-tokens/{made.json()['id']}"
    assert (await csrf_client.delete(base, headers=SV)).status_code == 403
    assert (
        await csrf_client.delete(base, headers={**SV, "X-CSRF-Token": token})
    ).status_code == 204


async def test_needs_events_view(world):
    client, cals = world
    none = as_user("sv")  # signed in, holds nothing
    assert (await client.get(url(cals["P"]), headers=none)).status_code == 403
    assert (await _create(client, cals["P"], headers=none)).status_code == 403


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client):
    client = multi_client
    install_directory(client.app)
    install_members(client.app, {"a": {"sv", "se", "m"}, "b": {"sv", "se", "m"}})
    cals_a, cals_b = await _calendars(client, "a"), await _calendars(client, "b")
    in_a = {**SV, "X-Test-Tenant": "a"}
    in_b = {**SV, "X-Test-Tenant": "b"}
    made = await client.post(url(cals_a["P"]), json={"label": "x"}, headers=in_a)
    assert made.status_code == 201
    base = f"{BASE.removesuffix('/calendars')}/feed-tokens"
    assert (await client.delete(f"{base}/{made.json()['id']}", headers=in_b)).status_code == 404
    assert (await client.get(url(cals_a["P"]), headers=in_b)).status_code == 404  # a's calendar
    assert (
        await client.post(url(cals_a["P"]), json={"label": "x"}, headers=in_b)
    ).status_code == 404
    assert (await client.get(url(cals_b["P"]), headers=in_b)).status_code == 200
    assert (await client.delete(f"{base}/{made.json()['id']}", headers=in_a)).status_code == 204
