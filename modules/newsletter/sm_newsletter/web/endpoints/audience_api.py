"""``GET /lists/{list_type_key}/fields`` (what a segment rule may name) and
``/audience-count`` (how many confirmed subscribers an audience reaches; a tag
or segment also needs ``records.view``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import SubscriberFilterError, caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import require_list
from sm_newsletter.campaigns.audience import AUDIENCE_ALL, audience_count
from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.segments import store
from sm_newsletter.segments.rules import ops_for
from sm_newsletter.web.schemas.segments import CountOut, ListFieldOut

router = APIRouter(dependencies=[Depends(bind_admin)])


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
    await require_list(
        db, tenant_id=tenant, list_type_key=list_type_key, roles=caller_roles(request)
    )
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
    if audience != AUDIENCE_ALL:
        # A tag or segment count evaluates subscriber fields (a rule can name
        # ``sm_email``), so it needs ``records.view``; the whole list does not,
        # so the editor's estimate still works for a campaign author without it.
        await RequiresPermission(constants.PERM_RECORDS_VIEW)(request)
    roles = caller_roles(request)
    await require_list(db, tenant_id=tenant, list_type_key=list_type_key, roles=roles)
    count = await audience_count(
        db, tenant_id=tenant, list_type_key=list_type_key, audience=audience, roles=roles
    )
    return CountOut(count=count)
