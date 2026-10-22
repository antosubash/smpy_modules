"""How an import matches its rows to existing records.

An import row whose match key resolved nothing but whose ``uuid`` is already
here is a row error — reported by the dry run, refused or skipped by the apply
— and never an ``IntegrityError`` escaping the report as a 500; and
``match_by=slug`` matches on the canonical (slugified) form of the cell, which
is the only form a write ever stores.
"""

from __future__ import annotations

import json

import pytest
from sm_records.contracts.io import ImportFormat, OnError
from sm_records.models import RecordType
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services.errors import ImportRefused
from sm_records.services.import_ import ImportOptions, import_records

from tests.field_builders import text

# ---------------------------------------------------------------------------
# a stale match key over an existing uuid is a row error, not a 500
# ---------------------------------------------------------------------------


async def stale_slug_file(db, settings) -> tuple[RecordType, str]:
    """A ``note`` whose slug has moved on since the file naming it was written.

    The shape an operator produces by exporting a type and then renaming one
    record in the admin: the row's ``uuid`` is still here, its ``slug`` is not.
    """
    note = await type_service.create_type(
        db,
        key="note",
        label="Note",
        settings=settings,
        fields_raw=[text("title")],
        slug_field="title",
    )
    record = await record_service.create_record(
        db, note, data={"title": "hello"}, settings=settings
    )
    document = {
        "type": {"key": "note"},
        "records": [
            {
                "uuid": record.uuid,
                "slug": "hello",
                "data": {"title": "hello"},
                "version": record.version,
            }
        ],
    }
    record.slug = "hello-renamed"
    db.add(record)
    await db.flush()
    return note, json.dumps(document)


async def test_the_dry_run_reports_a_uuid_that_match_by_slug_did_not_find(db, settings):
    note, document = await stale_slug_file(db, settings)
    report = await import_records(
        db,
        note,
        document,
        fmt=ImportFormat.JSON,
        options=ImportOptions(match_by="slug", dry_run=True),
        settings=settings,
    )
    assert (report.created, report.updated, report.failed) == (0, 0, 1)
    assert "match_by='slug'" in report.errors[0].message


async def test_the_apply_refuses_the_same_row_rather_than_raising_integrityerror(db, settings):
    """The whole point: the write path used to re-stamp the file's uuid with a
    bare flush, and the document table's unique index answered with an
    ``IntegrityError`` nothing maps — a 500 on a file the dry run had just
    promised."""
    note, document = await stale_slug_file(db, settings)
    with pytest.raises(ImportRefused) as refused:
        await import_records(
            db,
            note,
            document,
            fmt=ImportFormat.JSON,
            options=ImportOptions(match_by="slug", dry_run=False, force=True),
            settings=settings,
        )
    assert refused.value.report.failed == 1
    assert refused.value.report.created == 0


async def test_on_error_skip_skips_the_row_and_writes_nothing(db, settings):
    note, document = await stale_slug_file(db, settings)
    report = await import_records(
        db,
        note,
        document,
        fmt=ImportFormat.JSON,
        options=ImportOptions(match_by="slug", dry_run=False, force=True, on_error=OnError.SKIP),
        settings=settings,
    )
    assert (report.created, report.updated, report.failed) == (0, 0, 1)


# ---------------------------------------------------------------------------
# match_by=slug matches the canonical form
# ---------------------------------------------------------------------------


async def test_match_by_slug_matches_the_slugified_cell(db, settings):
    """A hand-written file says ``Hello World``; the record it is about holds
    ``hello-world``, because that is the only form a write ever stores."""
    note = await type_service.create_type(
        db,
        key="note",
        label="Note",
        settings=settings,
        fields_raw=[text("title")],
        slug_field="title",
    )
    record = await record_service.create_record(
        db, note, data={"title": "Hello World"}, settings=settings
    )
    assert record.slug == "hello-world"
    document = json.dumps([{"slug": "Hello World", "data": {"title": "Hello World Updated"}}])

    dry = await import_records(
        db,
        note,
        document,
        fmt=ImportFormat.JSON,
        options=ImportOptions(match_by="slug", dry_run=True, force=True),
        settings=settings,
    )
    assert (dry.created, dry.updated, dry.failed) == (0, 1, 0)

    applied = await import_records(
        db,
        note,
        document,
        fmt=ImportFormat.JSON,
        options=ImportOptions(match_by="slug", dry_run=False, force=True),
        settings=settings,
    )
    assert (applied.created, applied.updated, applied.failed) == (0, 1, 0)
    assert record.data["title"] == "Hello World Updated"
