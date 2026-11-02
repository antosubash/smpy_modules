"""Write dependencies for the ``/images/{image_id}`` and ``/groups/{group_id}``
routes: withheld before refused.

``RequiresResource`` answers 404 for a target the caller cannot see and 403 for
one they can see but may not change. A viewer (who cannot edit the collection)
does not see a withheld image (its redaction is pending) or a group whose every
image is withheld: the read routes answer those with :func:`errors.absent`. A
write refusing them with 403 would say the id exists, so here the viewer's
withholding is applied *before* the action refusal, and a withheld target gets
the same framework 404 an unknown id gets. A target the viewer can see keeps the
framework's 403 (``PermissionDenied("resource:<action>")``), unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from simple_module_core.permission_denied import PermissionDenied
from simple_module_core.resources import ACTION_DELETE, ACTION_EDIT
from simple_module_db.deps import get_db
from simple_module_db.resource_policy import load_authorized
from simple_module_hosting.resource_deps import RESOURCE_PERMISSION_PREFIX, resource_principal

from sm_images.core.access import POLICY, can_edit, group_collection_stmt, image_collection_stmt
from sm_images.models import Collection

__all__ = [
    "GroupCollectionEdit",
    "ImageCollectionEdit",
    "ImageCollectionOwner",
    "RequiresWritable",
]

Probe = Callable[[Any, Collection, uuid.UUID], Awaitable[Any]]
"""Loads the target as a viewer reads it; raises ``errors.absent()`` when withheld."""


async def _image(db: Any, collection: Collection, target: uuid.UUID) -> Any:
    from sm_images.web.services import gallery

    return await gallery.get(db, collection, target, gated=True)


async def _group(db: Any, collection: Collection, target: uuid.UUID) -> Any:
    from sm_images.web.services import groups

    return await groups.get(db, collection, target, gated=True)


class RequiresWritable:
    """``RequiresResource(POLICY, action, loader)``, but a caller who cannot
    edit is refused a withheld target with the absent 404, not the 403."""

    def __init__(self, action: str, loader: Callable[..., Any], param: str, probe: Probe) -> None:
        self.action, self.param, self.probe = action, param, probe

        async def dependency(
            request: Request, stmt: Any = Depends(loader), db: Any = Depends(get_db)
        ) -> Collection:
            return await self.check(request, stmt, db)

        self.dependency = dependency

    async def check(self, request: Request, stmt: Any, db: Any) -> Collection:
        who = await resource_principal(request)
        row, allowed = await load_authorized(db, POLICY, who, self.action, stmt)
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        if allowed:
            return row
        if not await can_edit(db, who, row):  # a viewer: what they read is gated
            await self.probe(db, row, uuid.UUID(str(request.path_params[self.param])))
        raise PermissionDenied(f"{RESOURCE_PERMISSION_PREFIX}{self.action}")


def _writable(action: str, loader: Callable[..., Any], param: str, probe: Probe) -> Any:
    return Depends(RequiresWritable(action, loader, param, probe).dependency)


ImageCollectionEdit = Annotated[
    Collection, _writable(ACTION_EDIT, image_collection_stmt, "image_id", _image)
]
ImageCollectionOwner = Annotated[
    Collection, _writable(ACTION_DELETE, image_collection_stmt, "image_id", _image)
]
GroupCollectionEdit = Annotated[
    Collection, _writable(ACTION_EDIT, group_collection_stmt, "group_id", _group)
]
