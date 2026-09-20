"""Phase 5 core review — the import and expansion halves. Each test failed
before its fix.

Three findings:

* an import row whose match key resolved nothing but whose ``uuid`` is already
  here is a row error — reported by the dry run, refused or skipped by the
  apply — and never an ``IntegrityError`` escaping the report as a 500;
* a relation nobody filled in expands to nothing rather than to one phantom
  ``dangling`` reference reading ``uuid: "None"``;
* ``match_by=slug`` matches on the canonical (slugified) form of the cell,
  which is the only form a write ever stores.

The schema half is in ``test_review_fixes_round5.py``.
"""

from __future__ import annotations

import json

import pytest
from sm_records.contracts.io import ImportFormat, OnError
from sm_records.models import RecordType
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services.errors import ImportRefused
from sm_records.services.expand import expand
from sm_records.services.import_ import ImportOptions, import_records
from sm_records.settings import RecordsSettings

from tests.round5_helpers import rel, text


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


# ---------------------------------------------------------------------------
# 2 — a stale match key over an existing uuid is a row error, not a 500
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
# 3 — an empty relation expands to nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("many", [False, True])
@pytest.mark.parametrize("stored", [None, []])
async def test_an_empty_relation_expands_to_no_entries(db, settings, many, stored):
    """``validate_payload`` dumps every declared key, so *every* record of a
    type with a relation nobody filled in holds ``None`` under it — which used
    to expand to one ``dangling`` chip reading ``uuid: "None"``."""
    await type_service.create_type(
        db, key="person", label="Person", settings=settings, fields_raw=[text("name")]
    )
    memo = await type_service.create_type(
        db,
        key="memo",
        label="Memo",
        settings=settings,
        fields_raw=[text("title"), rel("about", "person", many=many)],
    )
    record = await record_service.create_record(
        db, memo, data={"title": "nothing here"}, settings=settings
    )
    assert record.data["about"] is None
    if stored is not None:
        # ``[]`` is what a to-many holds once the last reference is removed,
        # and what a to-one can hold on a row written before
        # ``_check_ref_list``. Neither validates as *input* on a to-one, so it
        # is written the way such a row got there.
        record.data = {**record.data, "about": stored}
        db.add(record)
        await db.flush()
    out = await expand(db, memo, [record], ["about"])
    assert out[record.uuid]["about"] == []


async def test_an_unparsable_entry_inside_a_list_still_keeps_its_slot(db, settings):
    """The positional rule M4 added is about entries *inside* a non-empty
    list, and it stays: the expansion is rendered beside ``data[key]``."""
    person = await type_service.create_type(
        db, key="person", label="Person", settings=settings, fields_raw=[text("name")]
    )
    memo = await type_service.create_type(
        db,
        key="memo",
        label="Memo",
        settings=settings,
        fields_raw=[text("title"), rel("about", "person", many=True)],
    )
    ada = await record_service.create_record(db, person, data={"name": "Ada"}, settings=settings)
    record = await record_service.create_record(
        db,
        memo,
        data={"title": "m", "about": [{"type": "person", "uuid": ada.uuid}]},
        settings=settings,
    )
    # Written behind the module's back, the way a row that predates
    # ``_check_ref_list`` looks.
    record.data = {"title": "m", "about": [None, {"type": "person", "uuid": ada.uuid}]}
    db.add(record)
    await db.flush()

    out = await expand(db, memo, [record], ["about"])
    assert [ref.dangling for ref in out[record.uuid]["about"]] == [True, False]


# ---------------------------------------------------------------------------
# 4 — match_by=slug matches the canonical form
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
