"""The contract reads exactly what records' own reads allow: its results equal records' public
list for the public, and records' list for a signed-in viewer (published ones), so the two cannot
drift."""

from __future__ import annotations

from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordStatus
from sm_records.records.index._predicates import FilterOp
from sm_records.records.index.query import Filter, Sort
from sm_records.records.services import records as record_service
from sm_records.records.services._listing import list_records
from sm_records.records.services.public import list_public_records

from tests.contracts.dated_support import HI, LO, caller, make_type, read

BOTH = RecordsSettings(content_locales=("en", "de"))
WINDOW = [Filter("due", FilterOp.GTE, LO), Filter("due", FilterOp.LT, HI)]


async def seed(db, key, **cols):
    rtype = await make_type(db, key, **cols)
    for title, due, status, locale in (
        ("in window", "2026-07-05", RecordStatus.PUBLISHED, "en"),
        ("also", "2026-07-20", RecordStatus.PUBLISHED, "en"),
        ("german", "2026-07-06", RecordStatus.PUBLISHED, "de"),
        ("draft", "2026-07-07", RecordStatus.DRAFT, "en"),
        ("outside", "2026-09-01", RecordStatus.PUBLISHED, "en"),
    ):
        await record_service.create_record(
            db,
            rtype,
            data={"title": title, "due": due},
            settings=BOTH,
            status=status,
            locale=locale,
        )
    gone = await record_service.create_record(
        db,
        rtype,
        data={"title": "trashed", "due": "2026-07-08"},
        settings=BOTH,
        status=RecordStatus.PUBLISHED,
        locale="en",
    )
    await record_service.soft_delete_record(db, rtype, gone, settings=BOTH)
    return rtype


async def test_the_public_result_equals_records_public_list(db):
    rtype = await seed(db, "pub_t", is_public=True, translatable=True)
    for locale in ("en", "de"):
        theirs = await list_public_records(
            db, rtype, settings=BOTH, locale=locale, filters=WINDOW, sorts=[Sort("due")]
        )
        mine = await read(db, "pub_t", who=None, locale=locale, settings=BOTH)
        assert [h.uuid for h in mine.hits] == [r.uuid for r in theirs.items]
        assert mine.hits  # the comparison is not vacuous


async def test_the_signed_in_result_equals_records_list_for_that_viewer(db):
    rtype = await seed(db, "priv_t", allowed_roles=["editor"], translatable=True)
    theirs = await list_records(
        db, rtype, settings=BOTH, filters=WINDOW, sorts=[Sort("due")], page_size=100
    )
    published = [r.uuid for r in theirs.items if r.status == RecordStatus.PUBLISHED]
    allowed = await read(db, "priv_t", who=caller("editor"), settings=BOTH)
    assert [h.uuid for h in allowed.hits] == published and published
    assert (
        await read(db, "priv_t", who=caller("viewer"), settings=BOTH)
    ).hits == []  # as the API refuses
