"""The "My registrations" screen: for anyone signed in, not behind ``records.view``.

It only renders the shell; the list and the cancel go through ``/api/records/registrations/mine``,
which reads the caller's own verified address and nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_inertia import InertiaResponse

from sm_records.core import constants, tenancy
from sm_records.web.endpoints.api._errors import RecordsViewErrorRoute
from sm_records.web.endpoints.api.registrations_mine import signed_in

__all__ = ["router"]

router = APIRouter(
    route_class=RecordsViewErrorRoute,
    dependencies=[Depends(tenancy.bind_admin), Depends(signed_in)],
)


@router.get("/registrations/mine", response_model=None)
async def my_registrations(request: Request, inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(constants._PAGE_MY_REGISTRATIONS, {})
