"""The share dialog's user picker.

The framework has no share UI, so images builds one against
``/api/sharing/shares`` and needs a way to find a grantee. This is it: owner or
``images.manage`` only (``CollectionOwner``, so an edit share is a 403), names
come from the framework's ``UserDirectory``, and on a multi-tenant host only
members of the bound tenant are offered - the picker must not reveal accounts
of other organisations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import NullUserDirectory, get_user_directory
from simple_module_db.deps import get_db

from sm_images import constants
from sm_images.access import CollectionOwner
from sm_images.deps import require_view
from sm_images.errors import ServiceUnavailable
from sm_images.schemas.collection import ShareCandidate
from sm_images.tenancy import TenancyMode, bound_tenant, mode_of, request_mode

router = APIRouter(prefix="/collections", tags=["shares"])


@router.get("/{collection_id}/share-candidates", dependencies=[require_view])
async def share_candidates(
    request: Request,
    collection: CollectionOwner,
    q: str = Query("", max_length=100),
    db=Depends(get_db),
) -> list[ShareCandidate]:
    directory = get_user_directory(request.app)
    if isinstance(directory, NullUserDirectory):
        error = ServiceUnavailable(constants.DIRECTORY_UNAVAILABLE_DETAIL)
        error.code = constants.DIRECTORY_UNAVAILABLE_CODE
        raise error
    found = await directory.search(db, q.strip() or None, limit=constants.CANDIDATES_SCAN)
    users = [u for u in found if u.is_active and u.id != collection.owner_id]
    if request_mode(request, mode_of(request.app)) is not TenancyMode.SINGLE:
        # Fail closed: no membership store means nobody can be vouched for.
        members = await tenant_member_ids(request.app, db, bound_tenant(), [u.id for u in users])
        users = [u for u in users if u.id in (members or set())]
    return [
        ShareCandidate(id=u.id, display_name=u.label, email=u.email)
        for u in users[: constants.CANDIDATES_MAX]
    ]
