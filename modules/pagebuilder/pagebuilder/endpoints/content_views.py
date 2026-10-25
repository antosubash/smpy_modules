"""Inertia view routes for the content-snapshot screens.

Split out of ``views.py`` to keep that file under the repo's 300-line cap,
which it crossed when the snapshot screens and the language controls landed in
the same release. The two routes here are a coherent pair — the snapshot list
and the approval screen for a staged restore — and neither shares anything but
the router with the page and media views next door.

Included into ``views.router`` rather than mounted separately, so the module
still registers one view router and the URLs are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_inertia import InertiaResponse

from pagebuilder.contracts.schemas import SnapshotRead
from pagebuilder.deps import get_snapshot_service
from pagebuilder.endpoints.api._deps import require_publish
from pagebuilder.permissions import PERM_PUBLISH
from pagebuilder.snapshots.service import SnapshotService

router = APIRouter()

_PAGE_SNAPSHOTS = "PageBuilder/ContentSnapshots"
_PAGE_IMPORT_REVIEW = "PageBuilder/ContentImportReview"


async def _pending_props(service: SnapshotService) -> dict | None:
    """The staged import as the screens want it, or ``None`` when nothing waits.

    Through ``service.readable``, so a contributed section's rows reach only a
    reader who may see them (#80). Only for a reader holding
    ``pagebuilder.publish`` — the gate on ``GET /imports/pending`` — so the
    screens cannot serve what the API refuses.
    """
    if service.access.lacking([PERM_PUBLISH]):
        return None
    staged = await service.pending()
    if staged is None:
        return None
    return (await service.readable(staged)).model_dump(mode="json")


@router.get("/content", response_model=None)
async def admin_content(
    inertia: InertiaDep,
    service: SnapshotService = Depends(get_snapshot_service),
) -> InertiaResponse:
    """Snapshot list, plus whether a restore is waiting on someone.

    Server-rendered so the list paints on first navigation; the pending banner
    travels with it because a restore awaiting approval is the one thing on
    this screen nobody should have to go looking for.

    The screen itself is not gated (the menu offers it to every pagebuilder
    role and the list is ungated in the API too); only the pending restore is.
    """
    snapshots = [
        SnapshotRead.model_validate(s).model_dump(mode="json") for s in await service.list()
    ]
    return await inertia.render(
        _PAGE_SNAPSHOTS,
        {
            "snapshots": snapshots,
            "pending": await _pending_props(service),
        },
    )


@router.get("/content/review", response_model=None, dependencies=[require_publish])
async def admin_content_review(
    inertia: InertiaDep,
    service: SnapshotService = Depends(get_snapshot_service),
) -> InertiaResponse:
    """The staged restore's plan, for an approver to accept or reject."""
    return await inertia.render(
        _PAGE_IMPORT_REVIEW,
        {"pending": await _pending_props(service)},
    )
