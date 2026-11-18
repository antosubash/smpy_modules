"""A calendar's old slug keeps resolving, to a calendar the public may see."""

from __future__ import annotations

import pytest
from sm_events.calendar import calendars
from sm_events.content import calendar_redirects as redirects
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, CalendarRedirect, Visibility
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch
from sqlalchemy import delete, func, select

from tests.pg_support import USING_POSTGRES
from tests.support.access import principal

WHO = principal("o", "events.view", "events.edit")


async def make(db, name="Team", **kw) -> Calendar:
    return await calendars.create_calendar(
        db, WHO, CalendarCreate(name=name, visibility=Visibility.PUBLIC, **kw), default_tz="UTC"
    )


async def rename(db, cal, slug) -> None:
    await calendars.update_calendar(db, cal, CalendarPatch(slug=slug))


async def rows(db) -> list[tuple[str, object]]:
    got = (await db.execute(select(CalendarRedirect))).scalars().all()
    return sorted((r.old_slug, r.calendar_id) for r in got)


async def test_rename_records(db):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    assert await redirects.resolve(db, "a") == "b"
    assert await rows(db) == [("a", cal.id)]


async def test_other_edits_record_nothing(db):
    cal = await make(db, slug="a")
    await calendars.update_calendar(db, cal, CalendarPatch(name="Renamed"))
    await rename(db, cal, "a")  # the same slug: not a rename
    assert await rows(db) == []


async def test_chain_collapses(db):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    await rename(db, cal, "gamma")
    assert await redirects.resolve(db, "a") == "gamma"
    assert await redirects.resolve(db, "b") == "gamma"
    assert await redirects.resolve(db, "gamma") is None  # the current slug is not a redirect


async def test_claim_releases(db):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    other = await make(db, "Other", slug="a")
    assert other.slug == "a"
    assert await redirects.resolve(db, "a") is None
    assert await rows(db) == []


async def test_derived_slug_claim_releases(db):
    cal = await make(db, slug="team")
    await rename(db, cal, "crew")
    again = await make(db, "Team")  # derived: team, which has a redirect
    assert again.slug == "team"
    assert await redirects.resolve(db, "team") is None


async def test_rename_back_removes(db):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    await rename(db, cal, "a")
    assert await redirects.resolve(db, "a") is None
    assert await redirects.resolve(db, "b") == "a"
    assert await rows(db) == [("b", cal.id)]


async def test_another_calendar_renamed_to_a_redirected_slug_releases_it(db):
    first = await make(db, slug="a")
    second = await make(db, "Second", slug="s")
    await rename(db, first, "b")
    await rename(db, second, "a")
    assert await redirects.resolve(db, "a") is None
    assert await rows(db) == [("s", second.id)]


async def test_existing_redirect_is_repointed(db):
    first = await make(db, slug="a")
    await rename(db, first, "b")
    second = await make(db, "Second", slug="s")
    # ``a`` is released by whoever claims it; if that calendar leaves again, the redirect is its.
    await rename(db, second, "a")
    await rename(db, second, "z")
    assert await redirects.resolve(db, "a") == "z"
    assert await rows(db) == [("a", second.id), ("s", second.id)]


@pytest.mark.parametrize("hide", ["internal", "private", "trashed"])
async def test_hidden_target(db, hide):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    assert await redirects.resolve(db, "a") == "b"
    if hide == "trashed":
        await calendars.trash_calendar(db, cal)
    else:
        await calendars.set_visibility(db, cal, Visibility(hide))
    assert await redirects.resolve(db, "a") is None
    assert await redirects.resolve(db, "b") is None
    assert await rows(db) == [("a", cal.id)]  # the row is kept: restoring brings it back


async def test_unknown_slug(db):
    assert await redirects.resolve(db, "never") is None


async def test_lost_race_on_the_redirect_row_repoints_it(db, monkeypatch):
    """Another request inserts the same ``old_slug`` between our read and our insert."""
    first = await make(db, slug="a")
    second = await make(db, "Second", slug="s")
    real = redirects._existing
    calls = 0

    async def blind_once(db_, slug):
        nonlocal calls
        calls += 1
        if calls == 1:
            db_.add(CalendarRedirect(calendar_id=second.id, old_slug=slug))
            await db_.flush()
            return None
        return await real(db_, slug)

    monkeypatch.setattr(redirects, "_existing", blind_once)
    await rename(db, first, "b")
    assert await rows(db) == [("a", first.id)]
    assert await redirects.resolve(db, "a") == "b"
    # The session is still usable.
    assert await db.scalar(select(func.count()).select_from(Calendar)) == 2


@pytest.mark.unbound_tenant
async def test_redirects_are_per_tenant(db):
    with tenant_scope("a"):
        cal = await make(db, slug="a")
        await rename(db, cal, "b")
        assert await redirects.resolve(db, "a") == "b"
    with tenant_scope("b"):
        assert await redirects.resolve(db, "a") is None
        other = await make(db, slug="a")  # free in this tenant, nothing to release
        assert other.slug == "a"
    with tenant_scope("a"):
        assert await redirects.resolve(db, "a") == "b"


@pytest.mark.skipif(not USING_POSTGRES, reason="SQLite does not enforce foreign keys here")
async def test_hard_delete_cascades(db):
    cal = await make(db, slug="a")
    await rename(db, cal, "b")
    table = Calendar.__table__  # type: ignore[attr-defined]
    await db.execute(delete(table).where(table.c.tenant_id == "default", table.c.id == cal.id))
    assert await rows(db) == []
