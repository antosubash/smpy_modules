"""``POST /campaigns/{id}/test-send``: the campaign to up to five addresses.

``bind_admin`` first on the router, the send permission after it; the CSRF
check wraps the whole API in ``module.py``. The campaign is reached through
``require_campaign`` with the caller's roles (ruling C4), so a campaign on a
list the caller may not read answers 404. The recipients a test may go to are
decided here, from the request (``test_recipients``, #348).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.test_recipients import allowed_recipients, spellings
from sm_newsletter.campaigns.test_send import send_test
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.test_send import TestSendIn, TestSendOut, TestSendResultOut

__test__ = False  # a module named test_*, not a pytest test module

router = APIRouter(dependencies=[Depends(bind_admin)])


@router.post(
    "/campaigns/{campaign_id}/test-send",
    response_model=TestSendOut,
    dependencies=[Depends(RequiresPermission(constants.PERM_SEND))],
)
async def post_test_send(
    campaign_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> TestSendOut:
    data = parse_payload(TestSendIn, payload)
    recipients = [str(r) for r in data.recipients]
    # Every form each address was typed in: suppressions hash the stored form.
    submitted = spellings(payload.get("recipients") if isinstance(payload, dict) else None)
    settings = getattr(request.app.state, constants.PACKAGE).settings
    allowed = await allowed_recipients(
        request,
        db,
        tenant_id=tenant,
        recipients=recipients,
        settings=settings,
        submitted=submitted,
    )
    results = await send_test(
        request.app,
        db,
        tenant_id=tenant,
        campaign_id=campaign_id,
        recipients=recipients,
        allowed=allowed,
        roles=caller_roles(request),
        spellings=submitted,
    )
    return TestSendOut(results=[TestSendResultOut.model_validate(r) for r in results])
