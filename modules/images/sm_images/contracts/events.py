"""Domain events other modules can subscribe to (bus: ``simple_module_core.events``).

Published after the commit (:mod:`sm_images.events`), inside the tenant they
describe, and carrying identifiers only. Every event names its ``tenant_id``
second: a slug and an id are only unique within a tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from simple_module_core.events import Event

__all__ = [
    "CollectionDeleted",
    "CollectionVisibilityChanged",
    "ImageAdded",
    "ImageProcessed",
    "PromptResultReviewed",
]


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


@dataclass
class ImageProcessed(Event):
    """Every enabled pipeline step of one processing cycle is final (completed,
    skipped or failed - not necessarily successful).

    Decided once per ``(tenant_id, image_id, processing_generation)``: a retry,
    force or re-run starts a new cycle and so a new event. Durable subscribers
    (``subscribe_durable``) get it from the outbox written in the deciding
    transaction - at least once, so deduplicate on that identity. Ordinary
    subscribers get a best-effort publish after the commit.
    """

    tenant_id: str
    collection_id: str
    image_id: str
    processing_generation: int


@dataclass
class PromptResultReviewed(Event):
    """A person accepted, corrected or rejected an AI result. Exactly one of
    ``image_id`` and ``group_id`` is set. The reviewed value itself is not
    carried: read it through :class:`PromptResultRead`."""

    tenant_id: str
    collection_id: str
    prompt_id: str
    result_id: int
    image_id: str | None
    group_id: str | None
    action: str
    review_status: str
    reviewed_by: str
