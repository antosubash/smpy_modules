"""``/newsletter/o/<token>.gif`` and ``/newsletter/c/<token>/<N>`` (T5, T6, T10-T13, B1, B3, B4).

The pixel answers the same GIF whatever the token; the click answers the
stored URL's 302 or one fixed 404. A token of another purpose is a forgery and
opens no session. Recording failures roll the whole transaction back and never
change the answer.
"""

from __future__ import annotations

import inspect
import logging

import pytest
from sm_newsletter.web.endpoints import tracking as endpoint
from sm_newsletter.web.endpoints.tracking import GIF
from sm_newsletter.web.services import tracking as service

from tests.support.tracking_http import (
    NO_STORE,
    answer,
    click_path,
    get,
    no_database,
    open_path,
    sign,
    snapshot,
    tracking_app,
)
from tests.support.tracking_world import clicks, counters, send_row, sent_campaign

pytestmark = pytest.mark.unbound_tenant

T = "default"
ZERO = {"open_unique_count": 0, "open_total_count": 0, "click_unique_count": 0,
        "click_total_count": 0}  # fmt: skip


@pytest.fixture
async def world():
    app, state = await tracking_app()
    cid, (sid,) = await sent_campaign(state, T)
    yield app, state, cid, sid
    await state.engine.dispose()


def _gif(res) -> None:
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/gif"
    assert res.content == GIF
    assert NO_STORE.items() <= dict(res.headers).items()


def _not_found(res) -> None:
    assert res.status_code == 404
    assert res.text == "Not found"
    assert res.headers["content-type"].startswith("text/plain")
    assert NO_STORE.items() <= dict(res.headers).items()


def test_the_gif_is_the_43_byte_transparent_pixel():
    assert len(GIF) == 43 and GIF.startswith(b"GIF89a")


@pytest.mark.parametrize(
    ("route", "minted"), [("o", "u"), ("o", "c"), ("c", "u"), ("c", "o")]
)  # fmt: skip
async def test_wrong_purpose_is_forged(world, monkeypatch, route, minted):
    app, state, cid, sid = world
    token = sign(minted, T, cid, sid)
    opened = no_database(monkeypatch, state)
    if route == "o":
        _gif(await get(app, open_path(token)))
    else:
        _not_found(await get(app, click_path(token)))
    assert opened == []


async def test_open_returns_gif_and_counts(world):
    app, state, cid, sid = world
    _gif(await get(app, open_path(sign("o", T, cid, sid))))
    assert (await counters(state, T, cid))["open_unique_count"] == 1
    assert (await counters(state, T, cid))["open_total_count"] == 1
    assert (await send_row(state, T, sid)).opened_at is not None


async def test_open_identical_for_real_forged_test(world):
    app, state, cid, sid = world
    paths = [
        open_path(sign("o", T, cid, sid)),
        open_path("test"),
        open_path("x.1.1.AAAA"),
        open_path("a" * 201),
        open_path(sign("o", T, cid, sid + 999)),
    ]
    answers = {repr(answer(await get(app, p))) for p in paths}
    assert len(answers) == 1
    assert await counters(state, T, cid) == {**ZERO, "open_unique_count": 1, "open_total_count": 1}


async def test_open_path_with_dotted_tenant():
    app, state = await tracking_app()
    try:
        cid, (sid,) = await sent_campaign(state, "org.a")
        _gif(await get(app, open_path(sign("o", "org.a", cid, sid))))
        assert (await counters(state, "org.a", cid))["open_total_count"] == 1
    finally:
        await state.engine.dispose()


async def test_click_redirects_to_exact_stored_url():
    app, state = await tracking_app()
    url = "https://e.org/p?a=1&b=2#x"
    try:
        cid, (sid,) = await sent_campaign(state, T, links=(url,))
        res = await get(app, click_path(sign("c", T, cid, sid)))
        assert res.status_code == 302
        assert res.headers["location"] == url
        assert NO_STORE.items() <= dict(res.headers).items()
        assert (await counters(state, T, cid))["click_unique_count"] == 1
        assert [(c.send_id, c.click_count) for c in await clicks(state, T)] == [(sid, 1)]
    finally:
        await state.engine.dispose()


async def test_click_unknown_position_404(world):
    app, state, cid, sid = world
    _not_found(await get(app, click_path(sign("c", T, cid, sid), 2)))
    assert await counters(state, T, cid) == ZERO


@pytest.mark.parametrize("position", ["0x1", "12345", "-1", "\uff11"])
async def test_click_bad_position_404(world, position):
    app, state, cid, sid = world
    token = sign("c", T, cid, sid)
    unknown = answer(await get(app, click_path(token, 2)))
    res = await get(app, click_path(token, position))
    _not_found(res)
    assert answer(res) == unknown
    assert await counters(state, T, cid) == ZERO


@pytest.mark.parametrize("token", ["x.1.1.AAAA", "test", "a" * 201])
async def test_click_forged_404_no_query(world, monkeypatch, token):
    app, state, _, _ = world
    opened = no_database(monkeypatch, state)
    _not_found(await get(app, click_path(token)))
    assert opened == []


async def test_click_missing_send_redirects_without_counting(world):
    app, state, cid, sid = world
    res = await get(app, click_path(sign("c", T, cid, sid + 999)))
    assert res.status_code == 302 and res.headers["location"] == "https://e.org/a"
    assert await counters(state, T, cid) == ZERO
    assert await clicks(state, T) == []


@pytest.mark.parametrize(
    ("opens", "clicks_on", "expected", "opened", "click_rows"),
    [
        (True, True, {"open_unique_count": 1, "open_total_count": 1,
                      "click_unique_count": 1, "click_total_count": 1}, True, 1),
        (True, False, {**ZERO, "open_unique_count": 1, "open_total_count": 1}, True, 0),
        (False, True, {**ZERO, "click_unique_count": 1, "click_total_count": 1}, False, 1),
        (False, False, ZERO, False, 0),
    ],
)  # fmt: skip
async def test_tracking_settings_matrix(opens, clicks_on, expected, opened, click_rows):
    app, state = await tracking_app(opens=opens, clicks_on=clicks_on)
    try:
        cid, (sid,) = await sent_campaign(state, T)
        _gif(await get(app, open_path(sign("o", T, cid, sid))))
        res = await get(app, click_path(sign("c", T, cid, sid)))
        assert res.status_code == 302 and res.headers["location"] == "https://e.org/a"
        assert await counters(state, T, cid) == expected
        row = await send_row(state, T, sid)
        assert (row.opened_at is not None) is opened
        assert row.open_count == (1 if opened else 0)
        assert (row.first_clicked_at is not None) is bool(click_rows)
        assert len(await clicks(state, T)) == click_rows
    finally:
        await state.engine.dispose()


async def test_commit_failure_still_answers(world, monkeypatch, caplog):
    app, state, cid, sid = world

    async def broken(_session):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(service, "finalize_session", broken)
    before = await snapshot(state, T, cid, [sid])
    open_token, click_token = sign("o", T, cid, sid), sign("c", T, cid, sid)
    with caplog.at_level(logging.WARNING, logger="sm_newsletter"):
        _gif(await get(app, open_path(open_token)))
        res = await get(app, click_path(click_token))
    assert res.status_code == 302 and res.headers["location"] == "https://e.org/a"
    assert await snapshot(state, T, cid, [sid]) == before
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all(str(sid) in r.getMessage() for r in warnings)
    for token in (open_token, click_token):
        assert token.rsplit(".", 1)[1] not in caplog.text


async def test_partial_failure_rolls_back(world, monkeypatch):
    app, state, cid, sid = world
    from sm_newsletter.tracking import record

    async def broken(*_a, **_k):
        raise RuntimeError("campaign row")

    monkeypatch.setattr(record, "_bump_campaign", broken)
    res = await get(app, click_path(sign("c", T, cid, sid)))
    assert res.status_code == 302
    row = await send_row(state, T, sid)
    assert (row.opened_at, row.first_clicked_at, row.open_count) == (None, None, 0)
    assert await clicks(state, T) == []


async def test_routes_ignore_client_identity(world):
    app, _, cid, sid = world
    headers = {"User-Agent": "Mail/1.0", "X-Forwarded-For": "203.0.113.9", "X-Real-IP": "x"}
    _gif(await get(app, open_path(sign("o", T, cid, sid)), headers))
    res = await get(app, click_path(sign("c", T, cid, sid)), headers)
    assert res.status_code == 302
    for module in (service, endpoint):
        source = inspect.getsource(module).lower()
        for needle in ("user_agent", "user-agent", "client.host", "request.client", "x-forwarded"):
            assert needle not in source, (module.__name__, needle)
