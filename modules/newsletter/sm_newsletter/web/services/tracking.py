"""What an open-pixel or click-redirect request records (T5, T6, T12).

**Order (T6).** The host secret, then the MAC with the route's own purpose
(``o`` or ``c``; a token minted for another purpose is a forgery, B1), then the
host-resolved tenant (S8). Only then is the token's tenant bound and a session
opened, so a forged token costs one HMAC and no query.

**Settings (T5)** are read from ``app.state.sm_newsletter.settings`` on every
request: with opens off the pixel records nothing, with clicks off the click
still redirects and records nothing. A click counts an implied open only while
open tracking is on (B3).

**The failure boundary (T12, B4)** is one ``try`` around the recording
statements *and* ``finalize_session``: any failure rolls the whole transaction
back, logs the send id at WARNING (never the token, A7) and the caller still
answers. The click's link read sits before it: a failure there is a 404.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import tokens
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.tokens import Purpose, SendToken
from sm_newsletter.tracking.record import link_url, record_click, record_open

__all__ = ["click_by_token", "open_by_token"]

logger = logging.getLogger(__name__)

_POSITION: Final = re.compile(r"[0-9]{1,4}")
_warned_no_secret = False


def _claims(
    app: Any, token: str, purpose: Purpose, resolved_tenant: str | None
) -> SendToken | None:
    global _warned_no_secret
    secret = tokens.host_secret(app)
    if not secret:
        if not _warned_no_secret:
            _warned_no_secret = True
            logger.error("newsletter: no host secret_key; opens and clicks are not recorded")
        return None
    claims = tokens.parse(secret, token, purpose=purpose)
    if claims is None:
        return None
    if resolved_tenant is not None and resolved_tenant != claims.tenant_id:
        return None
    return claims


async def _record(
    session: AsyncSession, send_id: int, write: Callable[[], Awaitable[object]]
) -> None:
    """Run ``write`` and commit; on any failure roll everything back and log."""
    try:
        await write()
        await finalize_session(session)
    except Exception:
        with suppress(Exception):  # closing the session discards the rest
            await session.rollback()
        logger.warning("newsletter: could not record tracking for send %s", send_id, exc_info=True)


async def open_by_token(
    app: Any, token: str, *, resolved_tenant: str | None, now: datetime
) -> None:
    """Count one open when the token verifies and open tracking is on."""
    claims = _claims(app, token, "o", resolved_tenant)
    if claims is None or not app.state.sm_newsletter.settings.tracking_opens:
        return
    with tenant_scope(claims.tenant_id):
        async with app.state.sm.db.session_factory() as session:
            await _record(
                session,
                claims.send_id,
                lambda: record_open(
                    session,
                    tenant_id=claims.tenant_id,
                    campaign_id=claims.campaign_id,
                    send_id=claims.send_id,
                    now=now,
                ),
            )


async def click_by_token(
    app: Any, token: str, position: str, *, resolved_tenant: str | None, now: datetime
) -> str | None:
    """The stored URL to redirect to, or ``None`` (the caller's 404)."""
    if not _POSITION.fullmatch(position):
        return None
    claims = _claims(app, token, "c", resolved_tenant)
    if claims is None:
        return None
    settings = app.state.sm_newsletter.settings
    with tenant_scope(claims.tenant_id):
        async with app.state.sm.db.session_factory() as session:
            try:
                link = await link_url(
                    session,
                    tenant_id=claims.tenant_id,
                    campaign_id=claims.campaign_id,
                    position=int(position),
                )
            except Exception:
                logger.warning("newsletter: could not read the link for send %s", claims.send_id)
                return None
            if link is None:
                return None
            link_id, url = link
            if settings.tracking_clicks:
                await _record(
                    session,
                    claims.send_id,
                    lambda: record_click(
                        session,
                        tenant_id=claims.tenant_id,
                        campaign_id=claims.campaign_id,
                        send_id=claims.send_id,
                        link_id=link_id,
                        now=now,
                        count_open=settings.tracking_opens,
                    ),
                )
            return url
