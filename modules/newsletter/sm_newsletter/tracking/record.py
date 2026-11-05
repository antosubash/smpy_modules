"""Counting opens and clicks without losing or double-counting under races.

Every unique count is a guarded ``UPDATE … WHERE <column> IS NULL`` whose
rowcount says who won (T9); totals are ``n = n + 1``; a click is one row per
``(send, link)`` that ``insert_ignore`` either creates or that gets its
``click_count`` bumped (T8). The module's one lock order, which ``cancel`` and
``sending.rows.record`` follow too: send rows, then click row, then campaign row.

The callers bind the tenant and commit with ``finalize_session``; nothing here
commits. Every statement pins ``tenant_id`` (and ``campaign_id`` on the send).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.urls import is_http_link
from sm_newsletter.core.upsert import affected_rows, insert_ignore
from sm_newsletter.models import Campaign, Click, Link, Send

__all__ = ["link_url", "record_click", "record_open"]


def _send_where(tenant_id: str, campaign_id: int, send_id: int) -> tuple:
    return (Send.tenant_id == tenant_id, Send.campaign_id == campaign_id, Send.id == send_id)


async def _rows(session: AsyncSession, stmt) -> int:
    return affected_rows(await session.execute(stmt), session.get_bind().dialect.name)


async def _bump_campaign(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, **deltas: int
) -> None:
    """One ``UPDATE campaign SET <counter> = <counter> + delta`` for the non-zero deltas."""
    sets = {name: getattr(Campaign, name) + by for name, by in deltas.items() if by}
    if not sets:
        return
    where = (Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
    await session.execute(update(Campaign).where(*where).values(**sets))


async def record_open(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, send_id: int, now: datetime
) -> bool:
    """Count one open of a send. ``False`` (nothing written) when the send is not there."""
    where = _send_where(tenant_id, campaign_id, send_id)
    bumped = update(Send).where(*where).values(open_count=Send.open_count + 1)
    if not await _rows(session, bumped):
        return False
    first = await _rows(
        session, update(Send).where(*where, Send.opened_at.is_(None)).values(opened_at=now)
    )
    await _bump_campaign(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        open_total_count=1,
        open_unique_count=first,
    )
    return True


async def link_url(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, position: int
) -> tuple[int, str] | None:
    """``(link id, url)`` of a campaign's tracked link, or ``None`` when it is
    absent or the stored value is not a plain http(s) URL (never redirect to it)."""
    stmt = select(Link.id, Link.url).where(
        Link.tenant_id == tenant_id, Link.campaign_id == campaign_id, Link.position == position
    )
    row = (await session.execute(stmt)).first()
    if row is None or not is_http_link(row.url):
        return None
    return int(row.id), str(row.url)


async def record_click(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    send_id: int,
    link_id: int,
    now: datetime,
    count_open: bool,
) -> bool:
    """Count one click. ``False`` when the send is not there.

    A click implies an open (T7) only while ``count_open`` (open tracking on, B3).
    """
    where = _send_where(tenant_id, campaign_id, send_id)
    implied = 0
    if count_open:
        implied = await _rows(
            session,
            update(Send)
            .where(*where, Send.opened_at.is_(None))
            .values(opened_at=now, open_count=Send.open_count + 1),
        )
    unique = await _rows(
        session,
        update(Send).where(*where, Send.first_clicked_at.is_(None)).values(first_clicked_at=now),
    )
    if not (implied or unique):
        exists = await session.execute(select(Send.id).where(*where))
        if exists.first() is None:
            return False
    fresh = await insert_ignore(
        session,
        Click.__table__,  # ty: ignore[unresolved-attribute]
        [
            {
                "tenant_id": tenant_id,
                "send_id": send_id,
                "link_id": link_id,
                "clicked_at": now,
                "click_count": 1,
            }
        ],
        conflict=["tenant_id", "send_id", "link_id"],
    )
    if not fresh:
        await session.execute(
            update(Click)
            .where(Click.tenant_id == tenant_id, Click.send_id == send_id, Click.link_id == link_id)
            .values(click_count=Click.click_count + 1)
        )
    await _bump_campaign(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        click_total_count=1,
        click_unique_count=unique,
        open_unique_count=implied,
        open_total_count=implied,
    )
    return True
