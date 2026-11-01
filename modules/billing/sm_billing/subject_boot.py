"""Boot-time handling of ``subject_mode`` (#274).

Runs from ``startup.run``, the first point the hydrated settings exist. The mode
is published on ``app.state`` for the request-time helpers in ``subjects``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from simple_module_core import get_module_package_name
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import select
from users.constants import USER_ROLE_NAME

from sm_billing import constants as c
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.models import Customer, Subscription, UsageGauge, UsageHold, UsagePeriod
from sm_billing.user_teardown import subscribe_user_teardown

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Modules whose workers meter on the tenant, whatever the mode. ai's
# request-time ``RequiresAiRequest`` is billing's ``RequiresQuota`` and bills the
# user; only its worker-side ``consume_requests`` (images' AI steps) bills the
# tenant, so ``ai.requests`` is split across the two subjects.
_TENANT_BILLED = {"sm_images": "images", "sm_ai": "ai"}


def installed_callers(app: FastAPI) -> list[str]:
    """The loaded modules that keep metering on the tenant."""
    loaded = {get_module_package_name(m) for m in app.state.sm.modules}
    return [name for pkg, name in _TENANT_BILLED.items() if pkg in loaded]


async def _has_default_rows(app: FastAPI) -> bool:
    async with app.state.sm.db.session_factory() as session:
        for model in (Subscription, UsagePeriod, UsageGauge, UsageHold, Customer):
            row = await session.execute(
                select(model.tenant_id).where(model.tenant_id == DEFAULT_TENANT_ID).limit(1)
            )
            if row.first() is not None:
                return True
    return False


async def apply_subject_mode(app: FastAPI) -> None:
    services = getattr(app.state, c.PACKAGE)
    mode = services.settings.subject_mode
    setattr(app.state, c.SUBJECTS_STATE_ATTR, mode)
    if mode != c.SUBJECT_MODE_USER:
        return
    if is_multi_tenant(app):
        raise RuntimeError(
            "billing subject_mode=user needs a single-tenant host (multi_tenant is on)"
        )
    # Ordinary users hold the "user" role; with no tenant roles in play it is
    # the only one that reaches them.
    app.state.sm.permissions.map_role(USER_ROLE_NAME, [c.PERM_VIEW, c.PERM_MANAGE])
    subscribe_user_teardown(app)  # a deleted user's subscription is canceled
    if await _has_default_rows(app):
        logger.warning(
            "billing.subject_mode.stranded_default_rows: subscriptions, usage, holds "
            'or a customer recorded under the "default" subject are not visible in '
            "user mode"
        )
    callers = installed_callers(app)
    if callers:
        logger.warning(
            "billing.subject_mode.tenant_billed_callers: %s meter on the tenant "
            '("default") from workers, not on a user; ai.requests charged in a '
            "request bills the user, so that meter is split across both subjects",
            ", ".join(callers),
        )
