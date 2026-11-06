"""``GET /lists/{list_type_key}/fields`` (what a segment rule may name) and
``/audience-count`` (how many confirmed subscribers an audience reaches)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import SubscriberFilterError, caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import readable_lists
from sm_newsletter.campaigns.audience import audience_count
from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidAudience
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.segments import store
from sm_newsletter.segments.rules import ops_for
from sm_newsletter.web.schemas.segments import CountOut, ListFieldOut

router = APIRouter(dependencies=[Depends(bind_admin)])
MAX_AUDIENCE_LEN = 140  # newsletter_campaign.audience


@router.get(
    "/lists/{list_type_key}/fields",
    response_model=list[ListFieldOut],
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def list_fields(
    list_type_key: str,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ListFieldOut]:
    readable = await readable_lists(db, tenant_id=tenant, roles=caller_roles(request))
    if list_type_key not in readable:
        raise NotFound()
    try:
        fields = await store.fields_for(db, tenant_id=tenant, list_type_key=list_type_key)
    except SubscriberFilterError:
        raise NotFound() from None
    return [ListFieldOut(**f.model_dump(), ops=list(ops_for(f))) for f in fields.values()]


@router.get(
    "/lists/{list_type_key}/audience-count",
    response_model=CountOut,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def count_audience(
    list_type_key: str,
    request: Request,
    audience: str = "all",
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    if len(audience) > MAX_AUDIENCE_LEN:  # here, not in the signature: a 422 never echoes it
        raise InvalidAudience()
    roles = caller_roles(request)
    if list_type_key not in await readable_lists(db, tenant_id=tenant, roles=roles):
        raise NotFound()
    count = await audience_count(
        db, tenant_id=tenant, list_type_key=list_type_key, audience=audience, roles=roles
    )
    return CountOut(count=count)
