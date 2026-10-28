"""What other modules may import from images (spec §7).

Events, the read-only schemas and the policy-filtered reads. Nothing else in
``sm_images`` is a stable surface. ``points`` joins in Task 26 (it needs the
map tables); ``register_step``/``register_preset`` arrive with the pipeline.
"""

from __future__ import annotations

from sm_images.contracts.events import (
    CollectionDeleted,
    CollectionVisibilityChanged,
    ImageAdded,
)
from sm_images.contracts.reads import get_collection, list_collections, rendition_url
from sm_images.contracts.schemas import CollectionPageRead, CollectionRead

__all__ = [
    "CollectionDeleted",
    "CollectionPageRead",
    "CollectionRead",
    "CollectionVisibilityChanged",
    "ImageAdded",
    "get_collection",
    "list_collections",
    "rendition_url",
]
