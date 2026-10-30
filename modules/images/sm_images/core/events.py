"""Publishing this module's events: after the commit, never inside it.

:func:`emit` queues on the framework's ``on_commit`` (``simple_module_db.callbacks``),
which runs only once ``finalize_session`` has committed and is discarded on a
rollback. The tenant bound when the event is queued is bound again around the
publish, so a subscriber finds it in ``current_tenant_id``.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from simple_module_db.callbacks import register_on_commit
from simple_module_db.listeners import current_tenant_id

from sm_images.contracts.events import (
    CollectionDeleted,
    CollectionVisibilityChanged,
    ImageAdded,
    PromptResultReviewed,
)
from sm_images.core.tenancy import bound_tenant, tenant_scope
from sm_images.models import Collection, Image, PromptResult

__all__ = ["deleted", "emit", "image_added", "result_reviewed", "visibility_changed"]


async def _publish(bus: Any, event: Any, tenant: str | None) -> None:
    if tenant is None:
        await bus.publish(event)
        return
    with tenant_scope(tenant):
        await bus.publish(event)


def emit(session: Any, bus: Any, event: Any) -> None:
    """Publish ``event`` on ``bus`` once ``session`` commits. No bus, no event."""
    if bus is None:
        return
    register_on_commit(session, partial(_publish, bus, event, current_tenant_id.get()))


def visibility_changed(collection: Collection, before: str) -> CollectionVisibilityChanged:
    return CollectionVisibilityChanged(
        tenant_id=bound_tenant(),
        collection_id=str(collection.id),
        slug=collection.slug,
        before=before,
        after=collection.visibility.value,
    )


def deleted(collection: Collection) -> CollectionDeleted:
    return CollectionDeleted(
        tenant_id=bound_tenant(), collection_id=str(collection.id), slug=collection.slug
    )


def image_added(image: Image, source: str) -> ImageAdded:
    return ImageAdded(
        tenant_id=bound_tenant(),
        collection_id=str(image.collection_id),
        image_id=str(image.id),
        source=source,
    )


def result_reviewed(
    row: PromptResult, collection_id: Any, action: str, reviewer: str
) -> PromptResultReviewed:
    return PromptResultReviewed(
        tenant_id=bound_tenant(),
        collection_id=str(collection_id),
        prompt_id=str(row.prompt_id),
        result_id=int(row.id or 0),
        image_id=str(row.image_id) if row.image_id else None,
        group_id=str(row.group_id) if row.group_id else None,
        action=action,
        review_status=row.review_status.value,
        reviewed_by=reviewer,
    )
