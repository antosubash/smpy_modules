"""A registration type, a published event, and what a visitor does (PR 9).

Builds on :mod:`tests.support.submissions_http`. The events module's tables share the database
(``tests.pg_support`` adds them), and the world is seeded through events' own models, so what the
registration code reads is exactly what a host has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from httpx import AsyncClient
from sm_records.core import boot
from sm_records.public_submissions import mail_runner

from tests.support.app_harness import ADMIN, field, roles
from tests.support.public_submissions_support import create
from tests.support.submissions_http import JSON, SUBMISSIONS, configure

TYPE = "event_registrations"
PROVIDER = "records:registration"
ADDRESS = "Guest@Example.org "
STORED = "guest@example.org"
SOON = datetime(2099, 7, 1, 8, tzinfo=UTC)  # 10:00 in Vienna; far enough that it never closes


def reg_fields() -> list[dict[str, Any]]:
    diet = field("diet", indexed=False)
    diet["constraints"] = {"max_length": 100}
    return [diet]


def reg_config(**overrides: Any) -> dict[str, Any]:
    return {"kind": "registration", "enabled": True, "public_fields": ["diet"], **overrides}


async def registration_type(client: AsyncClient, key: str = TYPE, **config: Any):
    return await create(client, key, fields=reg_fields(), config=reg_config(**config))


async def seed_event(db_state: Any, *, tenant: str = "default", **fields: Any) -> dict[str, Any]:
    """A public calendar and a published one-off with builtin registration of ``TYPE``."""
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import Calendar, Event, EventText, Visibility
    from sqlalchemy import select

    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            cal = (
                (await db.execute(select(Calendar).where(Calendar.slug == "pub"))).scalars().first()
            )
            if cal is None:
                cal = Calendar(slug="pub", name="Pub", owner_id="o", visibility=Visibility.PUBLIC)
                db.add(cal)
                await db.flush()
            values = {
                "status": "published",
                "starts_at": SOON,
                "ends_at": SOON + timedelta(hours=1),
                "timezone": "Europe/Vienna",
                "uid": "reg-1@simple-module-events",
                "registration_mode": "builtin",
                "registration_provider": PROVIDER,
                "registration_target": TYPE,
                "registration_capacity": 2,
                **fields,
            }
            event = Event(calendar_id=cal.id, **values)
            db.add(event)
            await db.flush()
            db.add(
                EventText(
                    event_id=event.id,
                    locale="en",
                    slug=f"open-day-{event.id.hex[:8]}",
                    title="Open day",
                )
            )
            await db.commit()
            return {"event_id": str(event.id), "key": str(event.id), "calendar_id": str(cal.id)}


@pytest_asyncio.fixture
async def reg_site(site):
    """``site`` with the landing pages, a registration type and one published event."""
    boot.mount_submission_views(site.app)
    configure(
        site,
        public_submissions_rate_per_ip="1000/minute",
        public_submissions_type_rate="1000/minute",
    )
    resp = await registration_type(site)
    assert resp.status_code == 201, resp.text
    site.event = await seed_event(site.db_state)  # type: ignore[attr-defined]
    return site


async def load_registration(client: AsyncClient, event: dict, key: str = TYPE, **query: str):
    params = {"event": event["event_id"], "occurrence": event["key"], **query}
    return await client.get(f"{SUBMISSIONS}/{key}/registration", params=params)


async def register(
    client: AsyncClient,
    address: Any = ADDRESS,
    *,
    name: str = "Ada",
    data: dict[str, Any] | None = None,
    event: dict | None = None,
    key: str = TYPE,
    token: str | None = None,
    **body: Any,
):
    event = event or client.event  # type: ignore[attr-defined]
    if token is None:
        loaded = (await load_registration(client, event, key)).json()
        token = loaded["definition"]["token"]
    payload = {
        "data": {"sm_email": address, "sm_name": name, **(data or {})},
        "token": token,
        **body,
    }
    response = await client.post(f"{SUBMISSIONS}/{key}/submit", json=payload, headers=JSON)
    await mail_runner.drain()
    return response


async def regs(client: AsyncClient, key: str = TYPE, *, trashed: bool = False) -> list:
    query = "?trashed=true" if trashed else ""
    resp = await client.get(f"/api/records/types/{key}/records{query}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


LINK = __import__("re").compile(r"https://site\.example/records/submissions/(confirm|cancel)\?\S+")


def reg_links(message: Any) -> dict[str, dict[str, str]]:
    """``{action: {"t": token, "l": locale}}`` from a registration mail's text."""
    from urllib.parse import parse_qs, urlsplit

    out: dict[str, dict[str, str]] = {}
    for match in LINK.finditer(message.text):
        query = parse_qs(urlsplit(match.group(0)).query)
        out[match.group(1)] = {name: values[0] for name, values in query.items()}
    return out


async def follow(client: AsyncClient, action: str, token: Any):
    return await client.post(f"{SUBMISSIONS}/{action}", json={"t": token})


async def single_opt_in(client: AsyncClient) -> None:
    from tests.support.public_submissions_support import update

    resp = await update(
        client,
        TYPE,
        public_submissions=reg_config(
            double_opt_in=False, consent={"required": True, "text": {"en": "I agree"}}
        ),
    )
    assert resp.status_code == 200, resp.text


async def seat_counts(site: Any) -> tuple[int, int]:
    """``(seat rows, sum of counters)``; asserts every counter equals its seat rows."""
    from collections import Counter

    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import RegistrationCount, RegistrationSeat
    from sqlalchemy import select

    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            seats = list((await db.execute(select(RegistrationSeat))).scalars())
            counters = list((await db.execute(select(RegistrationCount))).scalars())
    per = Counter((s.event_id, s.occurrence_key) for s in seats)
    assert {(c.event_id, c.occurrence_key): c.taken for c in counters if c.taken} == dict(per)
    return len(seats), sum(c.taken for c in counters)


def record_url(uuid: str, tail: str = "", key: str = TYPE) -> str:
    return f"/api/records/types/{key}/records/{uuid}{tail}"
