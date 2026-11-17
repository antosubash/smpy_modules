"""Slug derivation and the free-slug search."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sm_events.calendar.slugs import free_slug, slug_write, slugify
from sm_events.core.errors import SlugTaken
from sm_events.models import Calendar, Category
from sm_events.models.calendar import CALENDAR_SLUG_CONSTRAINT
from sqlalchemy.exc import IntegrityError


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


async def test_slug_write_propagates_not_null_failure_and_keeps_session_usable(db):
    with pytest.raises(IntegrityError):
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            db.add(Calendar(slug=None, name="Invalid", owner_id="o"))
    assert await free_slug(db, Calendar, "team") == "team"


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (
            'duplicate key value violates unique constraint "uq_events_calendar_tenant_slug"',
            SlugTaken,
        ),
        ("UNIQUE constraint failed: events_calendar.tenant_id, events_calendar.slug", SlugTaken),
        (
            'null value in column "owner_id" of relation "events_calendar" '
            "violates not-null constraint\n"
            "DETAIL: Failing row contains (default, slug, Invalid, null).",
            IntegrityError,
        ),
        (
            "UNIQUE constraint failed: events_category.tenant_id, events_category.slug",
            IntegrityError,
        ),
        ("NOT NULL constraint failed: events_calendar.slug", IntegrityError),
    ],
)
async def test_slug_write_matches_only_its_unique_constraint(message, error):
    # Dialect messages without a database server; failure happens before flush.
    db = SimpleNamespace(begin_nested=nullcontext)
    failure = IntegrityError("INSERT", {}, Exception(message))
    with pytest.raises(error) as caught:
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            raise failure
    if error is IntegrityError:
        assert caught.value is failure


async def test_real_unique_violation_becomes_slug_taken_and_session_survives(db):
    # A genuine duplicate on whichever database the suite runs on.
    db.add(Calendar(slug="dup", name="First", owner_id="o"))
    await db.flush()
    with pytest.raises(SlugTaken):
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            db.add(Calendar(slug="dup", name="Second", owner_id="o"))
    assert await free_slug(db, Calendar, "dup") == "dup-2"


async def test_real_unique_violation_of_another_constraint_propagates(db):
    # A category slug clash is a genuine unique violation, but not the calendar one.
    db.add(Category(slug="dup", names={"en": "A"}))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            db.add(Category(slug="dup", names={"en": "B"}))
