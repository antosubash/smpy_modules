"""Giving a seeded render the tracking placeholders and its link rows."""

from __future__ import annotations

from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender, Link
from sqlalchemy import update

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
