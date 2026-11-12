"""Page and media cards for another module's emails (newsletter).

Small read-only snapshots: what an email block needs to show a page or an
image, with the site-relative path the caller makes absolute itself. Built on
the same rules as :mod:`pagebuilder.contracts.search` (#130): the caller names
the tenant and it is pinned as a ``WHERE``. Unlike search, a scope here also
refuses a different bound tenant (``TenantIsolationError``) and binds one when
nothing is bound. The pattern is a ``LIKE`` pattern with ``\\`` as the escape; the limit is
checked by :func:`pagebuilder.contracts.search._checked_limit`.

Pages are published and not trashed only. Media are raster images only: SVG is
not rendered by most mail clients. Where pagebuilder is not mounted
(:func:`mounted` is false) every function answers nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from pydantic import BaseModel
from simple_module_db import (
    MissingTenantError,
    TenantIsolationError,
    current_tenant_id,
    is_valid_tenant_id,
    tenant_context,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from pagebuilder.contracts.search import _checked_limit
from pagebuilder.core import locales
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.media.media_files import media_url
from pagebuilder.models import NOT_TRASHED, MediaAsset, Page, PageStatus

__all__ = [
    "MediaCard",
    "PageCard",
    "get_page_card",
    "mounted",
    "search_media_cards",
    "search_page_cards",
]

# Any case, with or without parameters (``image/svg+xml; charset=utf-8``).
_SVG_PREFIX = "image/svg%"


class PageCard(BaseModel, frozen=True):
    """A published page, as an email card shows it."""

    id: int
    title: str
    excerpt: str
    image_url: str
    path: str
    """Site-relative, language-prefixed except for the default language."""
    locale: str


class MediaCard(BaseModel, frozen=True):
    """A raster image in the media library."""

    id: int
    filename: str
    content_type: str
    path: str
    """Site-relative URL the file is served at."""


def _services(app: Any) -> Any | None:
    return getattr(getattr(app, "state", None), "pagebuilder", None)


def mounted(app: Any) -> bool:
    """Whether pagebuilder is mounted on ``app`` (installed is not enough), so a
    caller never reads ``app.state.pagebuilder`` itself (#336)."""
    return _services(app) is not None


def _settings(app: Any) -> PagebuilderSettings | None:
    services = _services(app)
    settings = getattr(services, "settings", None)
    return settings if isinstance(settings, PagebuilderSettings) else None


@contextmanager
def _scope(tenant_id: str) -> Iterator[None]:
    """Re-entering the bound tenant is a no-op, another one is refused, and
    with none bound ``tenant_id`` is bound for the block."""
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    current = current_tenant_id.get()
    if current is not None and current != tenant_id:
        raise TenantIsolationError(
            f"cannot read tenant {tenant_id!r} inside a scope bound to {current!r}"
        )
    if current == tenant_id:
        yield
        return
    with tenant_context(tenant_id):
        yield


def _page_card(page: Page, settings: PagebuilderSettings) -> PageCard:
    return PageCard(
        id=cast(int, page.id),  # a stored row always has its id
        title=page.title,
        excerpt=page.meta_description or "",
        image_url=page.og_image or "",
        path=locales.public_path(settings.public_route_prefix, page.slug, page.locale),
        locale=page.locale,
    )


def _published(tenant_id: str) -> tuple[Any, ...]:
    return (NOT_TRASHED, Page.tenant_id == tenant_id, Page.status == PageStatus.PUBLISHED)


async def search_page_cards(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    pattern: str,
    limit: int = 20,
    locale: str | None = None,
) -> list[PageCard]:
    """Published pages in ``tenant_id`` whose title or slug match ``pattern``,
    newest first. Every language unless ``locale`` names one."""
    limit = _checked_limit(limit)
    settings = _settings(app)
    if settings is None:
        return []
    stmt = select(Page).where(
        *_published(tenant_id),
        or_(
            col(Page.title).ilike(pattern, escape="\\"), col(Page.slug).ilike(pattern, escape="\\")
        ),
    )
    if locale is not None:
        stmt = stmt.where(col(Page.locale) == locale)
    try:
        with _scope(tenant_id):
            rows = (
                await session.execute(stmt.order_by(col(Page.id).desc()).limit(limit))
            ).scalars()
            return [_page_card(row, settings) for row in rows]
    except MissingTenantError:
        return []


async def get_page_card(
    app: Any, session: AsyncSession, *, tenant_id: str, page_id: int
) -> PageCard | None:
    """The published, untrashed page ``page_id`` of ``tenant_id``, or ``None``."""
    settings = _settings(app)
    if settings is None:
        return None
    stmt = select(Page).where(*_published(tenant_id), col(Page.id) == page_id)
    try:
        with _scope(tenant_id):
            page = (await session.execute(stmt)).scalars().first()
            return None if page is None else _page_card(page, settings)
    except MissingTenantError:
        return None


async def search_media_cards(
    app: Any, session: AsyncSession, *, tenant_id: str, pattern: str, limit: int = 20
) -> list[MediaCard]:
    """Raster images in ``tenant_id`` whose name matches ``pattern``, newest first."""
    limit = _checked_limit(limit)
    settings = _settings(app)
    if settings is None:
        return []
    stmt = select(MediaAsset).where(
        col(MediaAsset.tenant_id) == tenant_id,
        MediaAsset.content_type.ilike("image/%"),  # type: ignore[attr-defined]
        ~func.lower(MediaAsset.content_type).like(_SVG_PREFIX),
        or_(
            col(MediaAsset.original_filename).ilike(pattern, escape="\\"),
            col(MediaAsset.filename).ilike(pattern, escape="\\"),
        ),
    )
    try:
        with _scope(tenant_id):
            rows = (
                await session.execute(stmt.order_by(col(MediaAsset.id).desc()).limit(limit))
            ).scalars()
            return [
                MediaCard(
                    id=cast(int, r.id),  # a stored row always has its id
                    filename=r.original_filename,
                    content_type=r.content_type,
                    path=media_url(settings.media_url_prefix, r.filename, tenant_id),
                )
                for r in rows
            ]
    except MissingTenantError:
        return []
