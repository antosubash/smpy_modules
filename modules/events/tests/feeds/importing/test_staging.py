"""Upload and the parse step: bounded reads, rights, verdicts, all-or-nothing staging."""

from __future__ import annotations

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import Forbidden, IcsInvalid, ImportBusy, ImportTooLarge, NotFound
from sm_events.core.settings import EventsSettings
from sm_events.feeds.importing import staging
from sm_events.models import Calendar, EventImport
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.staging_support import seed
from tests.support.access import principal

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
