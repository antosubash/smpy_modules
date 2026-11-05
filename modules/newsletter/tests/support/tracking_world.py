"""Giving a seeded render the tracking placeholders and its link rows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender, Click, Link, Send
from sqlalchemy import select, update

from tests.support.campaign_world import campaign_row, seed_campaign, seed_sends
from tests.support.sending import T

TARGET = "https://example.com/story?a=1&b=2"
TRACKED_HTML = (
    '<p>Hi {{first_name|there}}</p><a href="{{link:1}}">Story</a>'
    '<a href="{{unsubscribe_url}}">Unsubscribe</a>{{open_pixel}}'
)


async def track_render(state: Any, cid: int, *, tenant: str = T) -> None:
    """Swap the render's HTML for :data:`TRACKED_HTML` and store link 1."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            await db.execute(
                update(CampaignRender)
                .where(CampaignRender.tenant_id == tenant, CampaignRender.campaign_id == cid)
                .values(html=TRACKED_HTML)
            )
            db.add(Link(tenant_id=tenant, campaign_id=cid, position=1, url=TARGET))
            await finalize_session(db)


async def sent_campaign(
    state: Any,
    tenant: str = T,
    *,
    links: Sequence[str] = ("https://e.org/a",),
    recipients: int = 1,
) -> tuple[int, list[int]]:
    """A ``sent`` campaign with ``links`` (positions 1..n) and ``recipients``
    ``sent`` rows: its id and their send ids."""
    cid = await seed_campaign(state, tenant, status="sent")
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            for position, url in enumerate(links, 1):
                db.add(Link(tenant_id=tenant, campaign_id=cid, position=position, url=url))
            await finalize_session(db)
    return cid, await seed_sends(state, tenant, cid, ["sent"] * recipients)


async def counters(state: Any, tenant: str, campaign_id: int) -> dict[str, int]:
    """The campaign's four open and click counters."""
    campaign = await campaign_row(state, tenant, campaign_id)
    names = ("open_unique_count", "open_total_count", "click_unique_count", "click_total_count")
    return {name: getattr(campaign, name) for name in names}


async def set_send(state: Any, tenant: str, send_id: int, **values: Any) -> None:
    """Write ``values`` onto one send row directly."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            await db.execute(
                update(Send).where(Send.tenant_id == tenant, Send.id == send_id).values(**values)
            )
            await finalize_session(db)


async def send_row(state: Any, tenant: str, send_id: int) -> Send:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(Send).where(Send.tenant_id == tenant, Send.id == send_id)
            return (await db.execute(stmt)).scalars().one()


async def clicks(state: Any, tenant: str) -> list[Click]:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(Click).where(Click.tenant_id == tenant).order_by(Click.id)
            return list((await db.execute(stmt)).scalars())


async def link_ids(state: Any, tenant: str, campaign_id: int) -> list[int]:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(Link.id).where(Link.tenant_id == tenant, Link.campaign_id == campaign_id)
            return list((await db.execute(stmt.order_by(Link.position))).scalars())
