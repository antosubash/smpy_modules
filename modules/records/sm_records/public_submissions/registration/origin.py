"""Where an event's page and ``.ics`` live, for a mail: configuration only, never a request header.

**An outbound link is never derived from ``Origin``, ``Host``, ``X-Forwarded-*`` or ``Referer``**:
the route is anonymous, so a header is whatever the sender wrote, and a link built from one is
phishing through our mailer. The ``Origin`` check on the submission routes stays an allow-list
comparison that refuses a cross-site post; it is never a source of output.

The base is trusted configuration: on a single-tenant host the host's ``public_base_url`` (read
live from the app's settings, as the confirmation mail's own links are). On a multi-tenant host the
tenant's own site is ``<organisation slug>.<tenants.subdomain_base>`` on the host's scheme and port
(the rule newsletter's content links follow; the framework has no helper for it at this version).
If no trusted origin can be determined (no ``public_base_url``, no subdomain base, no organisation)
the answer is ``""`` and the mail carries no event link: never a guessed one.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from sm_records.core.tenancy import TenancyMode, mode_of
from sm_records.public_submissions.tokens import public_base_url

__all__ = ["event_base"]

logger = logging.getLogger(__name__)


def _multi_tenant(app: Any) -> bool:
    return mode_of(app) is TenancyMode.MULTI


async def _org_slug(app: Any, tenant_id: str, db: Any) -> str | None:
    try:
        from sqlalchemy import select
        from tenants.models import Tenant
    except ImportError:  # the tenants module is optional
        return None
    if db is None:
        return None
    return (
        await db.execute(select(Tenant.slug).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()


async def event_base(app: Any, tenant_id: str, db: Any) -> str:
    """The origin of ``tenant_id``'s public site, or ``""`` when none can be trusted."""
    base = public_base_url(app)
    if not base:
        return ""
    if not _multi_tenant(app):
        return base
    tenants = getattr(getattr(app.state, "tenants", None), "settings", None)
    sub = (getattr(tenants, "subdomain_base", "") or "").strip().strip(".").lower()
    if not sub:
        return ""
    slug = await _org_slug(app, tenant_id, db)
    if not slug:
        logger.info(
            "records: tenant %s has no organisation site; the mail has no event link", tenant_id
        )
        return ""
    parts = urlsplit(base)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return ""
    return f"{parts.scheme}://{slug}.{sub}{port}"
