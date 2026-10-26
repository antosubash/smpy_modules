"""Permission dependencies shared by every admin API sub-router.

Per-endpoint :class:`~pagebuilder.permissions.RequiresPermission` deps let
hosts run the editor → publisher workflow without granting every editor
publish rights.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from simple_module_core.permissions import grants
from simple_module_hosting.permissions import PermissionDenied, ensure_resolved_permissions

from pagebuilder.contracts.schemas import SnapshotCapabilities
from pagebuilder.permissions import (
    PERM_APPROVE,
    PERM_EDIT,
    PERM_PUBLISH,
    RequiresPermission,
)
from pagebuilder.snapshots.access import SectionAccess

require_edit = Depends(RequiresPermission(PERM_EDIT))
require_publish = Depends(RequiresPermission(PERM_PUBLISH))
require_approve = Depends(RequiresPermission(PERM_APPROVE))


async def _publish_or_approve(request: Request) -> None:
    """Either Import / Export permission: the one who stages a restore, or the one who
    approves it. Resolved like ``RequiresPermission`` (roles plus grant sources)."""
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    held = await ensure_resolved_permissions(request)
    if not (grants(held, PERM_PUBLISH) or grants(held, PERM_APPROVE)):
        raise PermissionDenied(PERM_PUBLISH)


require_publish_or_approve = Depends(_publish_or_approve)
"""Reading the staged restore or the snapshot list: whoever may stage it or approve it."""


def snapshot_capabilities(access: SectionAccess) -> SnapshotCapabilities:
    """Which Import / Export controls *access* may use, for the screen to offer."""
    return SnapshotCapabilities(
        publish=not access.lacking([PERM_PUBLISH]),
        approve=not access.lacking([PERM_APPROVE]),
    )
