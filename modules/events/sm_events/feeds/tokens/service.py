"""Creating, listing and revoking private feed links.

Rights here are the **owner's**, asked of the same policy every other read uses
(:func:`~sm_events.core.access.visible_calendars`): a link is offered only for a calendar the
caller may view, and only when their rights can be worked out without a session at all
(:func:`~sm_events.core.access.offline.offline_principal`), so nobody is handed a link that could
never serve anything. A person lists and revokes their own links; ``events.manage`` lists and
revokes anyone's. A link someone else holds, and one that does not exist, are the same
``NotFound``. Nothing here commits: the caller's request session does.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sm_events.calendar.slugs import is_slug_conflict
from sm_events.core import constants
from sm_events.core.access import visible_calendars
from sm_events.core.access.offline import offline_principal
from sm_events.core.errors import (
    Forbidden,
    NotFound,
    PrivateFeedsUnavailable,
    TokenLimit,
    UnknownLocale,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.tokens.codec import hash_token, new_token
from sm_events.models import Calendar, FeedToken
from sm_events.models.feed_token import TOKEN_HASH_CONSTRAINT

__all__ = ["Created", "create_token", "list_tokens", "revoke_token"]

logger = logging.getLogger(__name__)
_ATTEMPTS = 3
"""A 256-bit token never collides; the retry exists so a unique violation can only ever mean
"try another", never a 500."""


@dataclass(frozen=True)
class Created:
    token: FeedToken
    secret: str
    """The token itself: returned to the caller once and kept nowhere."""


def _locale(request: Any, requested: str | None) -> str:
    """The link's language: the one asked for (it must be a content locale), else the console's
    when that is one, else the default."""
    allowed = tuple(getattr(request.app.state, constants.PACKAGE).settings.content_locales)
    if requested is not None:
        if requested not in allowed:
            raise UnknownLocale
        return requested
    console = getattr(request.state, "locale", None)
    return console if console in allowed else allowed[0]


async def _viewable(db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID, *, lock: bool) -> None:
    """``NotFound`` unless ``who`` may view the (untrashed) calendar. ``lock`` takes its row, so
    two creates for one calendar count the caller's links one after the other."""
    stmt = visible_calendars(who).where(
        Calendar.id == calendar_id,
        Calendar.tenant_id == bound_tenant(),  # type: ignore[arg-type]
    )
    if lock:
        stmt = stmt.with_for_update()
    if who.user_id is None or (await db.execute(stmt)).scalar_one_or_none() is None:
        raise NotFound


async def create_token(
    db: Any,
    request: Any,
    who: ResourcePrincipal,
    calendar_id: uuid.UUID,
    *,
    label: str,
    locale: str | None,
    now: datetime,
) -> Created:
    """A new link for ``who`` on ``calendar_id``.

    ``NotFound`` for a calendar they may not view (or without ``events.view``),
    ``PrivateFeedsUnavailable`` when their rights cannot be derived without a session,
    ``TokenLimit`` at :data:`~sm_events.core.constants.FEED_TOKENS_PER_USER_CALENDAR`."""
    if not who.has(constants.PERM_VIEW):
        raise NotFound
    await _viewable(db, who, calendar_id, lock=True)
    tenant, user_id = bound_tenant(), who.user_id
    assert user_id is not None  # _viewable refused an anonymous principal
    own = await offline_principal(
        request.app, db, user_id=user_id, tenant_id=tenant, request=request
    )
    if own is None:
        raise PrivateFeedsUnavailable
    chosen = _locale(request, locale)
    active = (
        await db.execute(
            select(func.count())
            .select_from(FeedToken)
            .where(
                FeedToken.tenant_id == tenant,  # type: ignore[arg-type]
                FeedToken.calendar_id == calendar_id,  # type: ignore[arg-type]
                FeedToken.user_id == user_id,  # type: ignore[arg-type]
                FeedToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).scalar_one()
    if active >= constants.FEED_TOKENS_PER_USER_CALENDAR:
        raise TokenLimit
    for _ in range(_ATTEMPTS):
        secret = new_token()
        row = FeedToken(
            calendar_id=calendar_id,
            user_id=user_id,
            token_hash=hash_token(secret),
            label=label,
            locale=chosen,
            created_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError as exc:
            if not is_slug_conflict(exc, TOKEN_HASH_CONSTRAINT):
                raise
            continue
        return Created(token=row, secret=secret)
    raise RuntimeError("could not mint a unique feed token")  # unreachable in practice


async def list_tokens(
    db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID, *, everyone: bool
) -> list[FeedToken]:
    """The live links on a calendar the caller may view: their own, or with ``everyone`` all of
    them (``events.manage``). A revoked link is not listed."""
    if everyone and not who.has(constants.PERM_MANAGE):
        raise Forbidden
    await _viewable(db, who, calendar_id, lock=False)
    stmt = select(FeedToken).where(
        FeedToken.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        FeedToken.calendar_id == calendar_id,  # type: ignore[arg-type]
        FeedToken.revoked_at.is_(None),  # type: ignore[union-attr]
    )
    if not everyone:
        stmt = stmt.where(FeedToken.user_id == who.user_id)  # type: ignore[arg-type]
    stmt = stmt.order_by(FeedToken.created_at.desc(), FeedToken.id)  # type: ignore[union-attr]
    return list((await db.execute(stmt)).scalars())


async def revoke_token(
    db: Any, who: ResourcePrincipal, token_id: uuid.UUID, *, now: datetime
) -> None:
    """Retire a link at once. ``NotFound`` unless it is the caller's own or they hold
    ``events.manage`` (a missing link is the same answer). Revoking a revoked link changes
    nothing. Needs no access to the calendar: losing it must never stop someone retiring their
    own link."""
    row = (
        await db.execute(
            select(FeedToken).where(
                FeedToken.tenant_id == bound_tenant(),  # type: ignore[arg-type]
                FeedToken.id == token_id,  # type: ignore[arg-type]
            )
        )
    ).scalar_one_or_none()
    own = who.user_id is not None and row is not None and row.user_id == who.user_id
    if row is None or not (own or who.has(constants.PERM_MANAGE)):
        raise NotFound
    if row.revoked_at is None:
        row.revoked_at = now
        await db.flush()
