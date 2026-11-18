"""Upload and the parse step: bounded reads, rights, verdicts, all-or-nothing staging."""

from __future__ import annotations

import json

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import Forbidden, IcsInvalid, ImportBusy, ImportTooLarge, NotFound
from sm_events.core.settings import EventsSettings
from sm_events.feeds.importing import staging
from sm_events.feeds.importing.fence import claim
from sm_events.models import Calendar, EventImport, EventImportItem
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.staging_support import make_import, seed
from tests.support.access import principal
from tests.support.calendars import seed_event

V, E, M = "events.view", "events.edit", "events.manage"
LOCALES = ("en",)


class FakeUpload:
    """An ``UploadFile``'s read side: counts what was asked for."""

    def __init__(self, total: int, size: int | None = None) -> None:
        self.total, self.size, self.served = total, size, 0

    async def read(self, n: int) -> bytes:
        give = min(n, self.total - self.served)
        first = self.served == 0
        self.served += give
        return (b"BEGIN:VCALENDAR\r\n" + b"x" * give)[:give] if first else b"x" * give


async def test_upload_too_large_streams():
    upload = FakeUpload(21 * constants.IMPORT_MIB)
    limit = 5 * constants.IMPORT_MIB
    with pytest.raises(ImportTooLarge):
        await staging.read_upload(upload, limit=limit)
    assert upload.served <= limit + constants.IMPORT_READ_CHUNK  # never read on past the cap


async def test_a_declared_size_over_the_cap_is_refused_unread():
    upload = FakeUpload(10, size=50 * constants.IMPORT_MIB)
    with pytest.raises(ImportTooLarge):
        await staging.read_upload(upload, limit=constants.IMPORT_MIN_BYTES)
    assert upload.served == 0


async def test_read_upload_returns_the_bytes():
    class One:
        size = None

        def __init__(self) -> None:
            self.parts = [corpus.simple(), b""]

        async def read(self, _n):
            return self.parts.pop(0)

    assert await staging.read_upload(One(), limit=constants.IMPORT_MIN_BYTES) == corpus.simple()


@pytest.mark.parametrize(("stored", "clamped"), [(1, 64 * 1024), (10**9, 20 * 1024 * 1024)])
def test_clamp(stored, clamped):
    assert staging.effective_max_bytes(EventsSettings(import_max_bytes=stored)) == clamped
    assert staging.effective_max_bytes(EventsSettings()) == 5 * 1024 * 1024


async def test_sniff_on_upload():
    class Png:
        size = None
        sent = False

        async def read(self, _n):
            if self.sent:
                return b""
            self.sent = True
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with pytest.raises(IcsInvalid):
        await staging.read_upload(Png(), limit=constants.IMPORT_MIN_BYTES)


async def test_create_needs_manage_and_calendar(db):
    cals = await seed(db)
    with pytest.raises(Forbidden):  # may write events, but is no manager
        await staging.create_import(
            db,
            principal("o", V, E),
            calendar_id=cals["P"].id,
            filename="a.ics",
            data=corpus.simple(),
            now=utcnow(),
        )
    imp = await staging.create_import(
        db,
        principal("m", V, M),
        calendar_id=cals["P"].id,
        filename="a.ics",
        data=corpus.simple(),
        now=utcnow(),
    )
    assert (imp.status, imp.created_by, imp.size_bytes, imp.source) == (
        "uploaded",
        "m",
        len(corpus.simple()),
        corpus.simple(),
    )
    assert imp.grants == [M, V] or sorted(imp.grants) == [M, V]
    row = (await db.execute(select(Calendar).where(Calendar.id == cals["I"].id))).scalar_one()
    row.is_deleted = True
    await db.flush()
    with pytest.raises(NotFound):
        await staging.create_import(
            db,
            principal("m", V, M),
            calendar_id=cals["I"].id,
            filename="a.ics",
            data=corpus.simple(),
            now=utcnow(),
        )
    with pytest.raises(NotFound):
        await staging.create_import(
            db,
            principal("m", V, M),
            calendar_id=__import__("uuid").uuid4(),
            filename="a",
            data=b"",
            now=utcnow(),
        )


async def test_busy(db):
    cals = await seed(db)
    who = principal("m", V, M)
    for n in range(constants.IMPORT_ACTIVE_MAX):
        await staging.create_import(
            db,
            who,
            calendar_id=cals["P"].id,
            filename=f"{n}.ics",
            data=corpus.simple(),
            now=utcnow(),
        )
    with pytest.raises(ImportBusy):
        await staging.create_import(
            db, who, calendar_id=cals["P"].id, filename="x.ics", data=corpus.simple(), now=utcnow()
        )
    first = (await db.execute(select(EventImport).order_by(EventImport.id))).scalars().first()
    first.status = "done"  # a finished import no longer counts
    await db.flush()
    await staging.create_import(
        db, who, calendar_id=cals["P"].id, filename="y.ics", data=corpus.simple(), now=utcnow()
    )


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("plain.ics", "plain.ics"),
        ("../../etc/pass\x00wd.ics", "passwd.ics"),
        ("C:\\Users\\me\\cal.ics", "cal.ics"),
        ("a\u202eb\nc.ics", "abc.ics"),
        ("", "calendar.ics"),
        ("///", "calendar.ics"),
        ("x" * 500, "x" * 200),
    ],
)
def test_filename_is_a_safe_basename(raw, kept):
    assert staging.safe_filename(raw) == kept


async def _staged(db, data: bytes, *, tenant="default"):
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=data)
    await db.commit()
    got = await claim(db, tenant_id=tenant, import_id=imp.id, owner="w", now=utcnow())
    assert got.kind == "claimed"
    return cals, imp


async def test_parse_verdicts(db):
    cals = await seed(db)
    await seed_event(db, cals["P"], uid="old@x", status="published", revision=3)
    await seed_event(db, cals["P"], uid="gone@x", is_deleted=True)
    await seed_event(db, cals["I"], uid="other@x")
    data = corpus.calendar(
        *corpus.vevent("new@x"),
        *corpus.vevent("old@x"),
        *corpus.vevent("gone@x"),
        *corpus.vevent("other@x"),
        *corpus.vevent("bad@x", "RRULE:FREQ=SECONDLY"),
    )
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "staged"
    items = {
        i.uid: i
        for i in (await db.execute(select(EventImportItem).order_by(EventImportItem.seq))).scalars()
    }
    got = {uid: (i.verdict, i.reason) for uid, i in items.items()}
    assert got == {
        "new@x": ("new", None),
        "old@x": ("update", None),
        "gone@x": ("skip", "uid_in_trash"),
        "other@x": ("new", None),
        "bad@x": ("skip", "unsupported_rule"),
    }
    assert items["old@x"].expected_revision == 3 and items["old@x"].existing_event_id is not None
    assert [i.seq for i in items.values()] == [1, 2, 3, 4, 5]
    await db.refresh(imp)
    assert (imp.status, imp.source, imp.total) == ("staged", None, 5)
    assert imp.counts == {"new": 2, "update": 1, "skip": 2}
    assert imp.reasons["uid_in_trash"] == 1 and imp.reasons["unsupported_rule"] == 1
    assert (imp.lease_owner, imp.lease_until) == (None, None)


async def test_parse_payload_is_the_mapped_event_and_holds_no_personal_data(db):
    cals = await seed(db)
    data = corpus.calendar(
        *corpus.vevent(
            "p@x",
            "ATTENDEE;CN=Jane Doe:mailto:jane@example.com",
            "ORGANIZER:mailto:boss@example.com",
            "BEGIN:VALARM",
            "ATTACH:http://127.0.0.1/x",
            "END:VALARM",
        )
    )
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    item = (await db.execute(select(EventImportItem))).scalar_one()
    await db.refresh(imp)
    blob = json.dumps([item.payload, item.notes, item.title, imp.counts, imp.reasons, imp.dropped])
    for private in ("jane", "Jane", "boss", "example.com", "127.0.0.1"):
        assert private not in blob
    assert imp.dropped == {"ATTENDEE": 1, "ORGANIZER": 1, "VALARM": 1}
    assert item.payload["uid"] == "p@x" and item.payload["times"]["timezone"] == "UTC"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (corpus.invalid_utf8(), "ics_encoding"),
        (corpus.depth(4), "ics_invalid"),
        (corpus.events(constants.IMPORT_MAX_EVENTS + 1), "too_many_events"),
    ],
)
async def test_parse_failure_records_code(db, data, code):
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "failed"
    await db.refresh(imp)
    assert (imp.status, imp.error_code, imp.source) == ("failed", code, None)
    assert (await db.execute(select(EventImportItem))).scalars().all() == []
    assert imp.finished_at is not None and imp.lease_owner is None


async def test_parse_is_all_or_nothing(db, monkeypatch):
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=corpus.simple(5))
    await db.commit()
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await db.commit()
    monkeypatch.setattr(constants, "IMPORT_ITEM_CHUNK", 2)
    real = db.flush
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return await real(*a, **k)

    monkeypatch.setattr(db, "flush", flaky)
    with pytest.raises(RuntimeError):
        await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    monkeypatch.undo()
    await db.rollback()
    row = (await db.execute(select(EventImport))).scalar_one()
    assert row.status == "parsing" and row.source == corpus.simple(5)  # left for the janitor
    assert (await db.execute(select(EventImportItem))).scalars().all() == []


async def test_no_library_parser_runs(db, monkeypatch):
    import icalendar

    def refuse(*_a, **_k):
        raise AssertionError("an upload must never reach the iCalendar library")

    monkeypatch.setattr(icalendar.Calendar, "from_ical", refuse)
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=corpus.simple(2))
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "staged"


async def test_a_trashed_calendar_fails_the_import(db):
    cals = await seed(db)
    imp = await make_import(db, cals["P"])
    cals["P"].is_deleted = True
    await db.flush()
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "failed"
    await db.refresh(imp)
    assert (imp.error_code, imp.source) == ("import_failed", None)


async def test_categories_match_by_default_locale_name(db):
    from sm_events.models import Category

    cals = await seed(db)
    cat = Category(slug="talks", names={"en": "Talks", "de": "Vortraege"})
    db.add(cat)
    await db.flush()
    imp = await make_import(
        db, cals["P"], data=corpus.calendar(*corpus.vevent("c@x", "CATEGORIES:talks"))
    )
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    item = (await db.execute(select(EventImportItem))).scalar_one()
    assert item.payload["category_id"] == str(cat.id)
