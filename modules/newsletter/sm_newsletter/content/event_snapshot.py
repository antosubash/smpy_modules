"""An :class:`~sm_newsletter.content.integrations.EventHit` as an ``EventCard`` block's props.

The hit comes from the public contract, so only a published event of a public calendar can
get here; this module only fits it to what the body accepts. Text from elsewhere is stripped
of bidirectional overrides (they would reorder the text around it in a mail client) and clipped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sm_newsletter.content.blocks import EventCardProps
from sm_newsletter.content.card_text import (
    EXCERPT_MAX,
    LOCALE_MAX,
    PLACE_MAX,
    TITLE_MAX,
    fits,
    strip_bidi,
)
from sm_newsletter.content.integrations import EventHit
from sm_newsletter.content.urls import check_site_image, check_site_path
from sm_newsletter.core.errors import CardSourceGone


def _text(value: str, limit: int) -> str:
    return strip_bidi(value)[:limit]


def event_snapshot_props(hit: EventHit, *, block_id: str, now: datetime) -> dict[str, Any]:
    """The event card's props for ``hit``. A page or calendar address the body would refuse
    cannot be carded (:class:`CardSourceGone`); an image it would refuse is dropped."""
    if not (fits(check_site_path, hit.url) and fits(check_site_path, hit.ics_url)):
        raise CardSourceGone()
    props = {
        "id": block_id,
        "source_id": hit.source_id,
        "title": _text(hit.title, TITLE_MAX),
        "excerpt": _text(hit.excerpt, EXCERPT_MAX),
        "image_url": hit.image_url if fits(check_site_image, hit.image_url) else "",
        "url": hit.url,
        "ics_url": hit.ics_url,
        "locale": hit.locale[:LOCALE_MAX],
        "starts_at": hit.starts_at.isoformat(),
        "ends_at": hit.ends_at.isoformat(),
        "all_day": hit.all_day,
        "start_date": hit.start_date.isoformat() if hit.start_date else None,
        "end_date": hit.end_date.isoformat() if hit.end_date else None,
        "timezone": hit.timezone,
        "attendance_mode": hit.attendance_mode,
        "place": _text(hit.place, PLACE_MAX),
        "cancelled": hit.cancelled,
        "snapshot_at": now.isoformat(),
    }
    return EventCardProps.model_validate(props).model_dump(mode="json")
