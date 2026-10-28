"""Who may see or act on a collection, and so on everything inside it (spec §2).

One policy object, :data:`POLICY`, answers every question: list and count
statements go through :meth:`ImagesCollectionPolicy.filter`, a single row
through ``RequiresResource`` (:data:`CollectionView` and friends), and the
``sharing`` module through the ``images.collection`` resource type. An image
is visible exactly when its collection is (:func:`visible_images`).

========  =====================================================================
action    who
========  =====================================================================
view      owner, a view or edit share, ``images.manage``, ``public`` for
          anyone, ``internal`` for any signed-in principal
edit      owner, an edit share, ``images.manage`` (never ``public``/``internal``)
delete    owner, ``images.manage`` (shares never)
share     owner, ``images.manage`` (shares never)
========  =====================================================================

**No tenant predicate here.** Collections and shares carry
``MultiTenantMixin``; ``bind_admin``/``bind_public`` bind the tenant, and the
framework filters on it. That binding is also what makes ``internal`` mean "a
member of this tenant": a multi-tenant request resolves a tenant only for an
active member, and on a single-tenant host every user is one.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends
from sharing.policy import share_exists_for
from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_VIEW,
    ResourcePrincipal,
)
from simple_module_db.deps import get_db
from simple_module_db.resource_policy import OwnedResourcePolicy
from simple_module_hosting.resource_deps import RequiresResource
from sqlalchemy import or_
from sqlmodel import select

from sm_images import constants
from sm_images.errors import NotFound
from sm_images.models import Collection, Image, Visibility

COLLECTION_RESOURCE = "images.collection"
"""The ``sharing`` resource type, and ``ResourceShare.resource_type``."""

_SHARE_ACTIONS = frozenset({ACTION_VIEW, ACTION_EDIT})
"""What a share can ever grant. Enforced here as well as by the share roles,
so a future ``sharing`` role implying ``delete`` cannot widen images."""


class ImagesCollectionPolicy:
    """``OwnedResourcePolicy`` plus ``internal`` visibility (plan decision 2).

    Implements the framework's ``ResourcePolicy`` protocol. Owner, share and
    bypass all come from the wrapped policy; this class only adds the
    ``internal`` clause for a signed-in viewer.
    """

    def __init__(self) -> None:
        shares = share_exists_for(COLLECTION_RESOURCE, Collection.id)

        def share_exists(principal: ResourcePrincipal, action: str) -> Any:
            return shares(principal, action) if action in _SHARE_ACTIONS else None

        self.visibility_col: Any = Collection.visibility
        self.owned = OwnedResourcePolicy(
            Collection.owner_id,
            bypass_perm=constants.PERM_MANAGE,
            visibility_col=self.visibility_col,
            public_value=Visibility.PUBLIC,
            share_exists=share_exists,
        )

    @staticmethod
    def _member_view(principal: ResourcePrincipal, action: str) -> bool:
        return action == ACTION_VIEW and principal.user_id is not None

    def predicate(self, principal: ResourcePrincipal, action: str) -> Any:
        """The ``WHERE`` clause, or ``None`` when the principal bypasses it."""
        clause = self.owned.predicate(principal, action)
        if clause is None or not self._member_view(principal, action):
            return clause
        return or_(clause, self.visibility_col == Visibility.INTERNAL)

    def filter(self, principal: ResourcePrincipal, action: str, stmt: Any) -> Any:
        clause = self.predicate(principal, action)
        return stmt if clause is None else stmt.where(clause)

    def can(self, principal: ResourcePrincipal, action: str, obj: Any) -> bool:
        if self.owned.can(principal, action, obj):
            return True
        return self._member_view(principal, action) and obj.visibility == Visibility.INTERNAL


POLICY = ImagesCollectionPolicy()


def visible_collections(who: ResourcePrincipal, action: str) -> Any:
    """``SELECT Collection`` narrowed to what *who* may *action* (trash excluded)."""
    return POLICY.filter(who, action, select(Collection))


def visible_images(who: ResourcePrincipal, action: str) -> Any:
    """``SELECT Image`` whose collection *who* may *action*.

    The soft-delete filter drops trashed images on its own; a trashed
    *collection* is excluded explicitly, so its images vanish with it even
    where a caller widens the statement with ``include_deleted``.
    """
    stmt = (
        select(Image)
        .join(Collection, Image.collection_id == Collection.id)
        .where(Collection.is_deleted.is_(False))
    )
    return POLICY.filter(who, action, stmt)


def collection_stmt(collection_id: uuid.UUID) -> Any:
    """The unfiltered loader ``RequiresResource`` narrows through :data:`POLICY`."""
    return select(Collection).where(Collection.id == collection_id)


# No ``permission=``: an API token is refused on these routes until a route
# opts in by building its own ``RequiresResource(..., permission=...)``.
CollectionView = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_VIEW, collection_stmt))
]
CollectionEdit = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, collection_stmt))
]
CollectionOwner = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_DELETE, collection_stmt))
]
"""Owner or ``images.manage``: delete, visibility, shares, pipeline config,
deleting images and whole-collection re-runs."""


def image_collection_stmt(image_id: uuid.UUID) -> Any:
    """The collection holding ``image_id`` (an untrashed image), for the
    ``/images/{image_id}`` routes: the image is reachable exactly when its
    collection is, so the same policy decides, and a stranger's 404 is the one
    an unknown id gets."""
    return (
        select(Collection)
        .join(Image, Image.collection_id == Collection.id)
        .where(Image.id == image_id)
    )


ImageCollectionView = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_VIEW, image_collection_stmt))
]
ImageCollectionEdit = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, image_collection_stmt))
]
ImageCollectionOwner = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_DELETE, image_collection_stmt))
]


def can_view_original(
    who: ResourcePrincipal, image: Image, collection: Collection, *, protected: bool | None = None
) -> bool:
    """Whether *who* may fetch *image*'s original bytes.

    Precondition: both rows were loaded through :data:`POLICY` for ``view``.
    With no display copy the original *is* what everyone sees; with one (a
    blurred derivative, say) only the owner and ``images.originals.view``
    holders get the original. ``images.manage`` alone does not.

    ``protected`` overrides "has a display copy" for a caller that knows more:
    the serving route also protects an original whose display mutator has not
    settled yet (``sm_images.serving``).
    """
    if image.collection_id != collection.id:
        return False
    if not (image.display_key is not None if protected is None else protected):
        return True
    owner = who.user_id is not None and collection.owner_id == who.user_id
    return owner or who.has(constants.PERM_ORIGINALS)


async def public_collection(slug: str, db: Any = Depends(get_db)) -> Collection:
    """Dependency for the anonymous routes: a public, untrashed collection or 404.

    Public only, whoever asks: the anonymous surface never serves an internal
    or private collection, even to its owner. Mount under ``bind_public``.
    """
    stmt = select(Collection).where(
        Collection.slug == slug, Collection.visibility == Visibility.PUBLIC
    )
    found = (await db.execute(stmt)).scalars().first()
    if found is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    return found


__all__ = [
    "COLLECTION_RESOURCE",
    "POLICY",
    "CollectionEdit",
    "CollectionOwner",
    "CollectionView",
    "ImageCollectionEdit",
    "ImageCollectionOwner",
    "ImageCollectionView",
    "ImagesCollectionPolicy",
    "can_view_original",
    "collection_stmt",
    "image_collection_stmt",
    "public_collection",
    "visible_collections",
    "visible_images",
]
