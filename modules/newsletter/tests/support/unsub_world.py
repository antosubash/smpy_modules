"""A sent campaign with one ``sent`` row per tenant, for the unsubscribe page tests.

Every helper binds the tenant it is given: the tests that use them are
``unbound_tenant``, as a real anonymous request is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient
from simple_module_db import finalize_session
from sm_newsletter.core import constants, tokens
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send, Suppression
from sm_records.contracts.events import SubscriptionChanged
from sm_records.contracts.newsletter import subscribers_by_uuid
from sqlalchemy import select

from tests.support.app import SECRET, build_app
from tests.support.records_seed import LIST, seed_list, seed_subscriber

ONE_CLICK = {"List-Unsubscribe": "One-Click"}


@dataclass
class Sent:
    tenant: str
    email: str
    uuid: str
    campaign_id: int
    send_id: int

    @property
    def token(self) -> str:
        return tokens.sign(
            SECRET,
            purpose="u",
            tenant_id=self.tenant,
            campaign_id=self.campaign_id,
            send_id=self.send_id,
        )


async def sent_campaign(
    state: Any, tenant: str, email: str, *, new_list: bool = True, status: str = "confirmed"
) -> Sent:
    """In ``tenant``: the list (unless ``new_list`` is false), ``email`` on it with
    ``status``, and a ``sent`` campaign whose one ``sent`` row went to ``email``
    after the subscriber was written."""
    if new_list:
        await seed_list(state, tenant)
    uuid = await seed_subscriber(state, tenant, email, status)
    now = datetime.now(UTC)
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            campaign = Campaign(
                name="c",
                list_type_key=LIST,
                subject="Hello",
                status="sent",
                started_at=now,
                finished_at=now,
                recipient_count=1,
                sent_count=1,
            )
            db.add(campaign)
            await db.flush()
            send = Send(
                campaign_id=campaign.id, record_uuid=uuid, email=email, status="sent", sent_at=now
            )
            db.add(send)
            await finalize_session(db)
            return Sent(tenant, email, uuid, campaign.id, send.id)


async def app_with(*, multi: bool = False, **kw: Any) -> tuple[Any, Any, list[Any]]:
    """The app, its state and a spy on ``SubscriptionChanged`` on the app's bus."""
    app, state = await build_app(multi=multi, **kw)
    events: list[Any] = []

    async def spy(event: Any) -> None:
        events.append(event)

    app.state.sm.event_bus.subscribe(SubscriptionChanged, spy)
    return app, state, events


async def call(
    app: Any, method: str, token: str, *, data: Any = None, headers: dict | None = None
) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://h.example") as c:
        return await c.request(
            method, f"{constants.UNSUBSCRIBE_PREFIX}{token}", data=data, headers=headers
        )


async def status_of_uuid(state: Any, tenant: str, uuid: str) -> str | None:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            hits = await subscribers_by_uuid(db, tenant_id=tenant, type_key=LIST, uuids=[uuid])
    hit = hits.get(uuid)
    return None if hit is None else hit.status


async def status_of(state: Any, s: Sent) -> str | None:
    return await status_of_uuid(state, s.tenant, s.uuid)


async def suppressions(state: Any, tenant: str) -> list[tuple[str, str, str]]:
    table = Suppression.__table__  # ty: ignore[unresolved-attribute]
    stmt = (
        select(table.c.reason, table.c.list_type_key, table.c.source)
        .where(table.c.tenant_id == tenant)
        .order_by(table.c.id)
    )
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            return [tuple(r) for r in (await db.execute(stmt)).all()]


_COUNTERS = (
    "recipient_count",
    "sent_count",
    "failed_count",
    "bounced_count",
    "suppressed_count",
    "unsubscribe_count",
)


async def counters(state: Any, s: Sent) -> dict[str, int]:
    table = Campaign.__table__  # ty: ignore[unresolved-attribute]
    stmt = select(*(table.c[name] for name in _COUNTERS)).where(
        table.c.id == s.campaign_id, table.c.tenant_id == s.tenant
    )
    with tenant_scope(s.tenant):
        async with state.session_factory() as db:
            row = (await db.execute(stmt)).one()
    return dict(zip(_COUNTERS, row, strict=True))


async def snapshot(state: Any, *worlds: Sent) -> list[Any]:
    """Records statuses, suppressions and campaign counters of every world."""
    return [
        (await status_of(state, s), await suppressions(state, s.tenant), await counters(state, s))
        for s in worlds
    ]
