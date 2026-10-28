"""Domain events other modules can subscribe to (bus: ``simple_module_core.events``).

Published after the commit (:mod:`sm_images.events`), inside the tenant they
describe, and carrying identifiers only. Every event names its ``tenant_id``
second: a slug and an id are only unique within a tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from simple_module_core.events import Event

__all__ = ["CollectionDeleted", "CollectionVisibilityChanged", "ImageAdded"]


@dataclass
class CollectionVisibilityChanged(Event):
    """A collection moved between ``private``, ``internal`` and ``public``."""

    tenant_id: str
    collection_id: str
    slug: str
    before: str
    after: str


@dataclass
class CollectionDeleted(Event):
    """A collection was soft-deleted (reversible until the janitor purges it)."""

    tenant_id: str
    collection_id: str
    slug: str


@dataclass
class ImageAdded(Event):
    """An image row was committed (any ingest path). ``source`` names the path:
    ``upload`` for the client uploads, the import kind otherwise."""

    tenant_id: str
    collection_id: str
    image_id: str
    source: str
