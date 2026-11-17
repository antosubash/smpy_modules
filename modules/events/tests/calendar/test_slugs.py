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


class FakeDriverError(Exception):
    def __init__(self, message, sqlstate=None, constraint_name=None):
        super().__init__(message)
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def _wrapped(driver_error, *, adapter_sqlstate=None):
    """SQLAlchemy's asyncpg adapter: ``orig`` is its own error, the driver's is ``__cause__``."""
    adapter = Exception(f"<class 'asyncpg'>: {driver_error}")
    adapter.sqlstate = adapter_sqlstate  # type: ignore[attr-defined]
    adapter.__cause__ = driver_error
    return IntegrityError("INSERT", {}, adapter)


@pytest.mark.parametrize(
    ("driver_error", "error"),
    [
        (FakeDriverError("x", "23505", CALENDAR_SLUG_CONSTRAINT), SlugTaken),
        # A localised message: only the structured fields decide.
        (FakeDriverError("doppelter Schluessel", "23505", CALENDAR_SLUG_CONSTRAINT), SlugTaken),
        (FakeDriverError("x", "23505", "uq_events_category_tenant_slug"), IntegrityError),
        (FakeDriverError("x", "23505", None), IntegrityError),
        (
            FakeDriverError(
                f'duplicate key value violates unique constraint "{CALENDAR_SLUG_CONSTRAINT}"',
                "23503",
                CALENDAR_SLUG_CONSTRAINT,
            ),
            IntegrityError,
        ),
        (
            FakeDriverError(f'unique constraint "{CALENDAR_SLUG_CONSTRAINT}"', "23502", "other"),
            IntegrityError,
        ),
    ],
)
async def test_slug_write_classifies_postgres_by_sqlstate_and_constraint(driver_error, error):
    db = SimpleNamespace(begin_nested=nullcontext)
    failure = _wrapped(driver_error, adapter_sqlstate=driver_error.sqlstate)
    with pytest.raises(error) as caught:
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            raise failure
    if error is IntegrityError:
        assert caught.value is failure


async def test_postgres_message_text_alone_is_not_enough():
    db = SimpleNamespace(begin_nested=nullcontext)
    message = f'duplicate key value violates unique constraint "{CALENDAR_SLUG_CONSTRAINT}"'
    failure = IntegrityError("INSERT", {}, Exception(message))
    with pytest.raises(IntegrityError):
        async with slug_write(db, CALENDAR_SLUG_CONSTRAINT):
            raise failure


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


def test_sqlite_message_comes_from_the_constraints_own_columns():
    from sm_events.calendar.slugs import _sqlite_message

    assert _sqlite_message("uq_events_calendar_tenant_slug") == (
        "UNIQUE constraint failed: events_calendar.tenant_id, events_calendar.slug"
    )
    assert _sqlite_message("uq_events_event_text_slug") == (
        "UNIQUE constraint failed: events_event_text.tenant_id, "
        "events_event_text.locale, events_event_text.slug"
    )
    assert _sqlite_message("uq_no_such_constraint") is None
