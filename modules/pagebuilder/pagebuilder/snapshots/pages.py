"""Turning a ``Page`` row into bundle JSON and back.

Kept apart from capture and apply because ``PAGE_FIELDS`` is the part most
likely to drift as ``Page`` grows a column — a reviewer should be able to see
the whole list at once and notice what is missing from it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pagebuilder.models import Page, PageStatus

PAGE_FIELDS: tuple[str, ...] = (
    "title",
    "meta_title",
    "meta_description",
    "og_image",
    "canonical_url",
    "index_in_search",
    "json_ld",
    "show_in_header_nav",
    "show_in_footer",
    "is_template",
    "draft_data",
    "published_data",
)
"""Authored columns carried verbatim in a bundle.

Excluded on purpose: ``id`` and ``parent_id`` are host-local (the parent
travels as a slug); ``deleted_at`` because trashed pages are never captured;
``rejection_note`` because it is a workflow artefact rather than content; and
the ``AuditMixin`` timestamps, which describe this host's history rather than
the content's.
"""

_DATETIME_FIELDS: tuple[str, ...] = ("publish_at", "unpublish_at")
"""Schedules, carried as ISO-8601 strings because JSON has no datetime."""


def page_to_payload(page: Page, parent_slug: str | None) -> dict[str, Any]:
    """Serialise *page* for the bundle, with its parent named by slug."""
    payload: dict[str, Any] = {
        "slug": page.slug,
        "parent_slug": parent_slug,
        "status": page.status.value,
    }
    for field in PAGE_FIELDS:
        payload[field] = getattr(page, field)
    for field in _DATETIME_FIELDS:
        value: datetime | None = getattr(page, field)
        payload[field] = value.isoformat() if value is not None else None
    return payload


def apply_payload(page: Page, payload: dict[str, Any]) -> None:
    """Write *payload* onto *page*, leaving ``parent_id`` to the second pass.

    An absent *schedule* is written as ``None`` rather than skipped: restoring
    is not merging, so a schedule the bundle does not carry must be cleared,
    not inherited from whatever was there before.

    Other absent keys are left untouched. ``page_to_payload`` always emits
    every ``PAGE_FIELDS`` key, so a bundle this code wrote never has any — and
    ``plan._fields_differ`` deliberately compares only the keys a payload
    carries, so the plan an approver reads describes exactly this behaviour.
    """
    page.status = PageStatus(payload["status"])
    for field in PAGE_FIELDS:
        if field in payload:
            setattr(page, field, payload[field])
    for field in _DATETIME_FIELDS:
        raw = payload.get(field)
        setattr(page, field, datetime.fromisoformat(raw) if raw else None)
