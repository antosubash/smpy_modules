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

from pagebuilder.contracts.schemas import PendingImportRead, SnapshotRead
from pagebuilder.deps import get_snapshot_service
from pagebuilder.snapshots.service import SnapshotService

router = APIRouter()

_PAGE_SNAPSHOTS = "PageBuilder/ContentSnapshots"
_PAGE_IMPORT_REVIEW = "PageBuilder/ContentImportReview"


def _pending_props(staged: object | None) -> dict | None:
    """A staged import as the screens want it, or ``None`` when nothing waits."""
    if staged is None:
        return None
    return PendingImportRead.model_validate(staged).model_dump(mode="json")


@router.get("/content", response_model=None)
async def admin_content(
    inertia: InertiaDep,
    service: SnapshotService = Depends(get_snapshot_service),
) -> InertiaResponse:
    """Snapshot list, plus whether a restore is waiting on someone.

    Server-rendered so the list paints on first navigation; the pending banner
    travels with it because a restore awaiting approval is the one thing on
    this screen nobody should have to go looking for.
    """
    snapshots = [
        SnapshotRead.model_validate(s).model_dump(mode="json")
        for s in await service.list()
    ]
    return await inertia.render(
        _PAGE_SNAPSHOTS,
        {
            "snapshots": snapshots,
            "pending": _pending_props(await service.pending()),
        },
    )


@router.get("/content/review", response_model=None)
async def admin_content_review(
    inertia: InertiaDep,
    service: SnapshotService = Depends(get_snapshot_service),
) -> InertiaResponse:
    """The staged restore's plan, for an approver to accept or reject."""
    return await inertia.render(
        _PAGE_IMPORT_REVIEW,
        {"pending": _pending_props(await service.pending())},
    )
