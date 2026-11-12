"""The share dialog's user picker.

The framework has no share UI, so images builds one against
``/api/sharing/shares`` and needs a way to find a grantee. This is it: owner or
``images.manage`` only (``CollectionOwner``, so an edit share is a 403), names
come from the framework's ``UserDirectory``, and on a multi-tenant host only
members of the bound tenant are offered - the picker must not reveal accounts
of other organisations.

**Not a directory listing (#357).** On a single-tenant host there is no
membership to filter by, and anyone who can create a collection owns one, so an
empty or one-letter ``q`` used to page through every active account's name and
address. A query shorter than :data:`MIN_QUERY` characters (after trimming)
answers ``[]`` without asking the directory, and the route has its own per-user
rate (:data:`RATE`, registered by ``ImagesModule.register_rate_limits``) so the
remaining three-letter space cannot be walked quickly either.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, Query, Request
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import NullUserDirectory, get_user_directory
from simple_module_db.deps import get_db

from sm_images.core import constants
from sm_images.core.access import CollectionOwner
from sm_images.core.errors import ServiceUnavailable
from sm_images.core.tenancy import DEFAULT_TENANT, TenancyMode, bound_tenant, mode_of, request_mode
from sm_images.web.endpoints.deps import require_view
from sm_images.web.schemas.collection import ShareCandidate


def _unscoped_single(request: Request) -> bool:
    """True only for a single-tenant host where nothing upstream resolved
    another tenant. Anything else (multi, a mis-detected mount, an upstream
    tenant, a bound tenant other than the default) filters by membership."""
    if request_mode(request, mode_of(request.app)) is not TenancyMode.SINGLE:
        return False
    upstream = getattr(request.state, "tenant_id", None)
    return upstream in (None, DEFAULT_TENANT) and bound_tenant() == DEFAULT_TENANT


MIN_QUERY: Final = 3
"""Characters of ``q`` (trimmed) below which the picker answers nobody."""
RATE: Final = "60/minute"
"""Per signed-in user, through the framework's rate-limit middleware."""
PATH_PATTERN: Final = rf"^{constants.ROUTE_PREFIX_API}/collections/[^/]+/share-candidates$"
"""The route, as the rate-limit rule matches it."""

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
        raise ServiceUnavailable(
            constants.DIRECTORY_UNAVAILABLE_DETAIL, code=constants.DIRECTORY_UNAVAILABLE_CODE
        )
    term = q.strip()
    if len(term) < MIN_QUERY:
        return []
    found = await directory.search(db, term, limit=constants.CANDIDATES_SCAN)
    users = [u for u in found if u.is_active and u.id != collection.owner_id]
    if not _unscoped_single(request):
        # Fail closed: no membership store means nobody can be vouched for.
        members = await tenant_member_ids(request.app, db, bound_tenant(), [u.id for u in users])
        users = [u for u in users if u.id in (members or set())]
    return [
        ShareCandidate(id=u.id, display_name=u.label, email=u.email)
        for u in users[: constants.CANDIDATES_MAX]
    ]
