"""Campaigns in a given state, their render snapshot and their send rows.

Shared by the lifecycle, freeze, delivery and dispatcher tests. Every helper
opens a session of its own, bound to the tenant it is given, and commits it
with ``finalize_session``. Pair it with :func:`tests.support.sending.make_app`,
which seeds the list ``news`` in ``default``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, CampaignRender, Send
from sqlalchemy import select

from tests.support.sending import BASE_URL, BODY, NOW

RENDER_HTML = '<p>Hi {{first_name|there}}</p><a href="{{unsubscribe_url}}">Unsubscribe</a>'
RENDER_TEXT = "Hi {{first_name|there}}\n\nUnsubscribe: {{unsubscribe_url}}\n"
SENDER = "News <news@example.org>"


async def seed_campaign(
    state: Any,
    tenant: str,
    *,
    status: str = "draft",
    body: list[Any] = BODY,
    subject: str = "Hello",
    list_key: str = "news",
    started_at: datetime | None = None,
    scheduled_at: datetime | None = None,
) -> int:
    """A campaign of ``tenant`` written as-is (no validation); its id."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            campaign = Campaign(
                name="c",
                list_type_key=list_key,
                subject=subject,
                body=list(body),
                status=status,
                started_at=started_at,
                scheduled_at=scheduled_at,
            )
            db.add(campaign)
            await finalize_session(db)
            assert campaign.id is not None
            return campaign.id


async def seed_render(
    state: Any, tenant: str, campaign_id: int, *, public_base: str = BASE_URL
) -> None:
    """A render snapshot for ``campaign_id``, merge tags in place."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            db.add(
                CampaignRender(
                    campaign_id=campaign_id,
                    subject="Hello {{first_name|there}}",
                    html=RENDER_HTML,
                    text=RENDER_TEXT,
                    sender=SENDER,
                    reply_to=None,
                    public_base=public_base,
                    locale="en",
                    rendered_at=NOW,
                )
            )
            await finalize_session(db)


async def seed_sends(
    state: Any, tenant: str, campaign_id: int, statuses: Sequence[str], *, freeze_gen: int = 0
) -> list[int]:
    """One send row per status, addressed ``r<n>@example.org``; their ids, in order."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            rows = [
                Send(
                    campaign_id=campaign_id,
                    record_uuid=uuid4().hex,
                    email=f"r{n}@example.org",
                    status=status,
                    freeze_gen=freeze_gen,
                )
                for n, status in enumerate(statuses)
            ]
            db.add_all(rows)
            await finalize_session(db)
            return [row.id for row in rows if row.id is not None]


async def send_rows(state: Any, tenant: str, campaign_id: int) -> list[Send]:
    """The campaign's send rows, oldest first."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = (
                select(Send)
                .where(Send.tenant_id == tenant, Send.campaign_id == campaign_id)
                .order_by(Send.id)
            )
            return list((await db.execute(stmt)).scalars())


async def render_row(state: Any, tenant: str, campaign_id: int) -> CampaignRender | None:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(CampaignRender).where(
                CampaignRender.tenant_id == tenant, CampaignRender.campaign_id == campaign_id
            )
            return (await db.execute(stmt)).scalars().first()


async def campaign_row(state: Any, tenant: str, campaign_id: int) -> Campaign:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(Campaign).where(Campaign.tenant_id == tenant, Campaign.id == campaign_id)
            return (await db.execute(stmt)).scalars().one()


async def set_columns(state: Any, tenant: str, campaign_id: int, **values: Any) -> None:
    """Write ``values`` onto the campaign directly, around the API."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            campaign = await db.get(Campaign, campaign_id)
            assert campaign is not None
            for key, value in values.items():
                setattr(campaign, key, value)
            await finalize_session(db)
