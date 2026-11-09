"""Driving the open pixel and the click redirect over HTTP (Task 6).

The tests that use these are ``unbound_tenant``, as a real anonymous request
is; every seed helper binds the tenant it is given.
"""

from __future__ import annotations

from typing import Any

from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants, tokens
from sm_newsletter.core.tokens import Purpose

from tests.support.app import SECRET, build_app
from tests.support.tracking_world import clicks, counters, send_row

NO_STORE = {
    "cache-control": "no-store, no-cache, must-revalidate, private",
    "pragma": "no-cache",
    "expires": "0",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex",
}


async def tracking_app(*, multi: bool = False, opens: bool = True, clicks_on: bool = True):
    """The newsletter app with the two tracking settings pinned; ``(app, state)``."""
    return await build_app(
        multi=multi, settings={"tracking_opens": opens, "tracking_clicks": clicks_on}
    )


def sign(purpose: Purpose, tenant: str, campaign_id: int, send_id: int) -> str:
    return tokens.sign(
        SECRET, purpose=purpose, tenant_id=tenant, campaign_id=campaign_id, send_id=send_id
    )


def open_path(token: str) -> str:
    return f"{constants.OPEN_PREFIX}{token}.gif"


def click_path(token: str, position: object = 1) -> str:
    return f"{constants.CLICK_PREFIX}{token}/{position}"


async def get(app: Any, path: str, headers: dict | None = None) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://h.example") as c:
        return await c.get(path, headers=headers)


def answer(res: Any) -> tuple[int, bytes, dict[str, str]]:
    """Everything a client sees: status, body and headers."""
    return res.status_code, res.content, dict(res.headers)


def no_database(monkeypatch: Any, state: Any) -> list[int]:
    """Replace the session factory with one that records the call and raises."""
    opened: list[int] = []

    def refuse(*_a: Any, **_k: Any) -> Any:
        opened.append(1)
        raise AssertionError("no session may be opened")

    monkeypatch.setattr(state, "session_factory", refuse)
    return opened


async def snapshot(state: Any, tenant: str, campaign_id: int, send_ids: list[int]) -> dict:
    """Every counter, ``opened_at``/``first_clicked_at`` and click row of one campaign."""
    sends = []
    for sid in send_ids:
        row = await send_row(state, tenant, sid)
        sends.append((sid, row.opened_at, row.open_count, row.first_clicked_at))
    rows = [(c.send_id, c.link_id, c.click_count) for c in await clicks(state, tenant)]
    return {
        "counters": await counters(state, tenant, campaign_id),
        "sends": sends,
        "clicks": rows,
    }
