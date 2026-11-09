"""Where the renderer's bases, branding and footer copy come from (R6, R7, R12, C7, C8).

Never the request: scheduling renders once, in a request that may be anyone's,
and the worker that sends the result has none; the request ``Host`` is
spoofable. Two bases (ruling C7): ``content_base`` is the campaign tenant's
public origin, for its own links, images and cards; ``public_base`` is the
host's ``public_base_url``, for newsletter's own routes (unsubscribe, logo),
whose tenant comes from the token.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlsplit

from sm_newsletter.content.render.styles import is_color
from sm_newsletter.content.render.types import Branding, FooterCopy, RenderContext
from sm_newsletter.content.urls import absolute
from sm_newsletter.core import constants
from sm_newsletter.core.messages import host_locale, server_copy
from sm_newsletter.core.tenancy import TenancyMode, mode_of

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Newsletter"
_KEYS = ("footer_reason", "unsubscribe", "read_more")


def test_unsubscribe_url(base_url: str) -> str:
    """The unsubscribe link of a preview or test send: no send row, so no token (R1)."""
    return f"{base_url.rstrip('/')}{constants.PUBLIC_PREFIX}u/{constants.TEST_UNSUBSCRIBE_TOKEN}"


test_unsubscribe_url.__test__ = False  # type: ignore[attr-defined] - not a pytest test


def _branding(app: Any, public_base: str, from_name: str) -> Branding:
    """The SYSTEM theme (R7), never a tenant's override; its logo through newsletter's
    own platform-scoped route (C8). Without branding: the sender name and the default accent."""
    theme = getattr(getattr(app.state, "branding", None), "settings", None)
    if theme is None:
        return Branding(from_name or _FALLBACK_NAME, constants.DEFAULT_ACCENT, "")
    color = getattr(theme, "primary_color", "") or ""
    accent = color if is_color(color) else constants.DEFAULT_ACCENT
    file_id = getattr(theme, "logo_file_id", "") or ""
    logo = ""
    if file_id:
        logo = absolute(public_base, f"{constants.BRAND_LOGO_PATH}?v={quote(file_id, safe='')}")
    return Branding(getattr(theme, "app_name", "") or from_name or _FALLBACK_NAME, accent, logo)


def _footer(app: Any, app_name: str) -> FooterCopy:
    """The ``newsletter.email.*`` strings in the host's default language (R12),
    the same as the unsubscribe page's."""
    _, copy = server_copy(app, "email", _KEYS)
    reason = copy["footer_reason"].replace("{app_name}", app_name)
    return FooterCopy(reason=reason, unsubscribe=copy["unsubscribe"], read_more=copy["read_more"])


async def _org_slug(app: Any, tenant_id: str) -> str | None:
    try:
        from sqlalchemy import select
        from tenants.models import Tenant
    except ImportError:  # the tenants module is optional
        return None
    factory = getattr(getattr(app.state.sm, "db", None), "session_factory", None)
    if factory is None:
        return None
    async with factory() as session:
        return (
            await session.execute(select(Tenant.slug).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()


async def _content_base(app: Any, tenant_id: str, public_base: str) -> str:
    """``<scheme>://<org slug>.<subdomain_base>[:port]`` on a multi-tenant host that
    resolves organisations by subdomain; else the host's own origin. The framework
    has no helper for an organisation's canonical origin (0.0.42)."""
    tenants = getattr(getattr(app.state, "tenants", None), "settings", None)
    sub = (getattr(tenants, "subdomain_base", "") or "").strip().strip(".").lower()
    if not sub or not public_base or mode_of(app) is not TenancyMode.MULTI:
        return public_base
    slug = await _org_slug(app, tenant_id)
    if not slug:
        logger.warning("newsletter: tenant %r has no organisation slug", tenant_id)
        return public_base
    parts = urlsplit(public_base)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:  # a malformed port: the host's own origin, as with no slug
        logger.warning("newsletter: public_base_url has a malformed port")
        return public_base
    return f"{parts.scheme}://{slug}.{sub}{port}"


async def render_context(app: Any, *, tenant_id: str) -> RenderContext:
    """Everything :func:`~sm_newsletter.content.render.render` needs for ``tenant_id``."""
    host = app.state.sm.settings
    public_base = (getattr(host, "public_base_url", "") or "").rstrip("/")
    locale = host_locale(app)
    settings = getattr(app.state, constants.PACKAGE).settings
    branding = _branding(app, public_base, settings.from_name)
    return RenderContext(
        content_base=await _content_base(app, tenant_id, public_base),
        public_base=public_base,
        branding=branding,
        physical_address=settings.physical_address,
        footer=_footer(app, branding.app_name),
        locale=locale,
    )
