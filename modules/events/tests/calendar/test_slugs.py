"""Slug derivation and the free-slug search."""

from __future__ import annotations

from sm_events.calendar.slugs import free_slug, slugify
from sm_events.models import Calendar


def test_slugify():
    assert slugify("Team Ärger 2026!") == "team-arger-2026"
    assert slugify("!!!") == "calendar"
    long = slugify("word " * 40)
    assert len(long) <= 80 and not long.endswith("-")


async def test_free_slug_counts_up_and_sees_the_trash(db):
    assert await free_slug(db, Calendar, "team") == "team"
    db.add(Calendar(slug="team", name="T", owner_id="o"))
    db.add(Calendar(slug="team-2", name="T", owner_id="o", is_deleted=True))
    await db.flush()
    assert await free_slug(db, Calendar, "team") == "team-3"
