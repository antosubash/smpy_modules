"""The error classes events reports, and their ``{"detail", "code"}`` body."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sm_events.core import errors
from sm_events.core.errors import install_exception_handlers

CASES = [
    (errors.Stale, 409, "stale"),
    (errors.OverridesOrphaned, 409, "overrides_orphaned"),
    (errors.HasSubEvents, 409, "has_sub_events"),
    (errors.InvalidTransition, 409, "invalid_transition"),
    (errors.PublishRequired, 403, "publish_required"),
    (errors.InvalidRule, 422, "invalid_rrule"),
    (errors.InvalidTimes, 422, "invalid_local_time"),
    (errors.InvalidRange, 422, "invalid_range"),
    (errors.DefaultLocaleRequired, 422, "default_locale_required"),
    (errors.UnknownCategory, 422, "unknown_category"),
    (errors.UnknownType, 422, "unknown_type"),
    (errors.InvalidParent, 422, "invalid_parent"),
    (errors.ImmutableField, 422, "immutable_field"),
    (errors.NotRecurring, 422, "not_recurring"),
    (errors.NotAnOccurrence, 422, "not_an_occurrence"),
    (errors.DescriptionTooLong, 422, "description_too_long"),
    (errors.SlugReserved, 422, "slug_reserved"),
    # PR 5: private feeds and the import.
    (errors.TokenLimit, 409, "token_limit"),
    (errors.ImportBusy, 409, "import_busy"),
    (errors.ImportTenantBusy, 409, "import_busy_tenant"),
    (errors.ImportState, 409, "import_state"),
    (errors.ImportTooLarge, 413, "import_too_large"),
    (errors.IcsInvalid, 422, "ics_invalid"),
    (errors.PrivateFeedsUnavailable, 503, "private_feeds_unavailable"),
]

EXTRA_CODES = [
    (errors.InvalidRule, "rrule_frequency_refused"),
    (errors.InvalidRule, "start_not_in_rule"),
    (errors.InvalidTimes, "end_before_start"),
    (errors.InvalidTimes, "duration_too_long"),
    (errors.InvalidRange, "range_too_long"),
]


@pytest.mark.parametrize(("cls", "status", "code"), CASES)
async def test_new_codes(cls, status, code):
    assert cls().status_code == status
    assert cls().code == code
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise cls()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        got = await http.get("/boom")
    assert got.status_code == status
    body = got.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == code
    assert body["detail"]


@pytest.mark.parametrize(("cls", "code"), EXTRA_CODES)
def test_alternative_codes_keep_status(cls, code):
    exc = cls(code=code)
    assert exc.code == code
    assert exc.status_code == 422
    assert exc.detail


async def test_stale_carries_the_current_revision_in_a_header_not_the_body():
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise errors.Stale(7)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        got = await http.get("/boom")
    assert got.status_code == 409
    assert set(got.json()) == {"detail", "code"}
    assert got.headers["x-current-revision"] == "7"


def test_import_failure_carries_a_code_only():
    """Not an HTTP error: a parse step raises it, and the row keeps its code, never a message."""
    failure = errors.ImportFailure("too_many_events")
    assert failure.code == "too_many_events"
    assert not isinstance(failure, errors.EventsError)
    assert str(failure) == "too_many_events"


def _extension_cases():
    from sm_events.core import errors_extensions as ext

    return [
        (ext.UnknownSource, 422, "unknown_source"),
        (ext.BuiltinSource, 422, "builtin_source"),
        (ext.DuplicateSource, 422, "duplicate_source"),
        (ext.TooManySources, 422, "too_many_sources"),
        (ext.ExtraTooLarge, 422, "extra_too_large"),
        (ext.TypeNotInstalled, 422, "type_not_installed"),
        (ext.SourceUnavailable, 503, "source_unavailable"),
    ]


@pytest.mark.parametrize(("cls", "status", "code"), _extension_cases())
async def test_extension_codes(cls, status, code):
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/x")
    async def raiser():
        raise cls()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/x")
    assert response.status_code == status
    assert response.json() == {"detail": cls.detail, "code": code}


def _reminder_cases():
    from sm_events.core import errors_reminders as rem

    return [
        (rem.FollowLimit, 409, "follow_limit"),
        (rem.NotPublished, 409, "not_published"),
        (rem.InvalidLead, 422, "invalid_lead"),
        (rem.RemindersUnavailable, 503, "reminders_unavailable"),
    ]


@pytest.mark.parametrize(("cls", "status", "code"), _reminder_cases())
async def test_reminder_codes(cls, status, code):
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/x")
    async def raiser():
        raise cls()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/x")
    assert response.status_code == status
    assert response.json() == {"detail": cls.detail, "code": code}
