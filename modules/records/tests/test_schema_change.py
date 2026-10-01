"""The §8 pipeline: classify, dry-run, refuse or write. Design doc §8.2 to §8.6.

What these tests are really about is *what did not happen*. A refused change
must leave the type exactly as it was — not merely return a 409 and rely on
somebody rolling the session back — and an applied one must not have touched a
single record's payload. Both are asserted after every refusal and every
apply.

The ``_orphaned`` half of §8 lives in ``test_schema_orphaned.py``; the rebuild
that these leave enqueued lives in ``test_reindex_runner.py``.
"""

from __future__ import annotations

import pytest
from sm_records.constants import REINDEX_ALL
from sm_records.index.query import Filter, FilterOp, QueryError, build_query
from sm_records.services import records as record_service
from sm_records.services import schema_change
from sm_records.services import types as type_service
from sm_records.services.errors import Conflict, NotFound, SchemaChangeRefused


@pytest.fixture
def fields(field_def):
    return [field_def("title", "text"), field_def("sku", "text", indexed=False)]


async def make(db, settings, fields, **cols):
    return await type_service.create_type(
        db, key="product", label="Product", fields_raw=fields, settings=settings, **cols
    )


async def add(db, settings, rtype, data: dict):
    return await record_service.create_record(db, rtype, data=data, settings=settings)


def tightened(field_def, **constraints) -> dict:
    return {**field_def("sku", "text", indexed=False), "constraints": constraints}


async def apply_fields(db, settings, rtype, fields_raw=None, **kw):
    """``apply`` against ``rtype``'s own current version — it mutates the
    object it is given in place, so the caller's ``rtype.version`` is already
    the right ``expected_version`` for whatever call comes next."""
    return await schema_change.apply(
        db, rtype, fields_raw=fields_raw, expected_version=rtype.version, settings=settings, **kw
    )


async def rollback_to(db, settings, rtype, to_version, **kw):
    return await schema_change.rollback(
        db, rtype, to_version=to_version, expected_version=rtype.version, settings=settings, **kw
    )


async def test_preview_reports_the_records_that_would_fail_and_writes_nothing(
    db, settings, fields, field_def
):
    rtype = await make(db, settings, fields)
    await add(db, settings, rtype, {"title": "One", "sku": "AB"})
    await add(db, settings, rtype, {"title": "Two", "sku": "ABCDEF"})

    diff, report = await schema_change.preview(
        db, rtype, [fields[0], tightened(field_def, min_length=5)], settings
    )

    assert diff.changes[0].what == "constraint_tightened"
    assert (report.checked, report.failing) == (2, 1)
    assert report.sample[0].display_title == ""
    assert report.sample[0].errors[0]["field"] == "sku"
    assert not report.clean
    assert (rtype.schema_version, rtype.version) == (1, 1)


async def test_preview_of_an_additive_change_skips_the_scan_but_reports_the_real_count(
    db, settings, fields, field_def
):
    """Nothing additive can invalidate a record, so the scan that could only
    ever report zero is skipped — but ``checked`` must still be the type's
    real record count, or "N checked, 0 would fail" lies about N."""
    rtype = await make(db, settings, fields)
    await add(db, settings, rtype, {"title": "One"})
    await add(db, settings, rtype, {"title": "Two"})

    diff, report = await schema_change.preview(
        db, rtype, [*fields, field_def("stock", "integer", indexed=False)], settings
    )
    assert diff.kind.value == "additive"
    assert (report.checked, report.failing) == (2, 0)
    assert report.clean


async def test_a_display_field_only_preview_reports_an_index_affecting_change(db, settings, fields):
    """A pointer-only preview (``fields`` unchanged, only ``display_field``
    moved) must not come back empty: it enqueues a whole-type rebuild (§18
    Q2) like any other index-affecting change. Omitting the argument, or
    resending it unchanged, must not manufacture a change out of nothing."""
    rtype = await make(db, settings, fields, display_field="title")
    await add(db, settings, rtype, {"title": "One"})

    diff, report = await schema_change.preview(db, rtype, fields, settings, display_field="sku")
    assert diff.kind.value == "index_affecting"
    assert [c.what for c in diff.changes] == ["display_field_changed"]
    assert (diff.changes[0].before, diff.changes[0].after) == ("title", "sku")
    assert (report.checked, report.failing) == (1, 0)  # not restrictive

    unchanged, _ = await schema_change.preview(db, rtype, fields, settings)
    same, _ = await schema_change.preview(db, rtype, fields, settings, display_field="title")
    assert unchanged.changes == () == same.changes


async def test_an_additive_change_applies_to_a_populated_type(db, settings, fields, field_def):
    rtype = await make(db, settings, fields)
    record = await add(db, settings, rtype, {"title": "One"})
    before = dict(record.data)

    updated, diff = await schema_change.apply(
        db,
        rtype,
        fields_raw=[*fields, field_def("stock", "integer", indexed=False)],
        expected_version=1,
        settings=settings,
    )

    assert updated.schema_version == 2
    assert updated.version == 2
    assert [f["key"] for f in updated.fields] == ["title", "sku", "stock"]
    # The record is untouched: payloads migrate on their own next write (§8.3).
    assert record.data == before
    assert record.schema_version == 1
    assert diff.keys(*[c.kind for c in diff.changes]) == ("stock",)


async def test_a_restrictive_change_is_refused_and_writes_nothing(db, settings, fields, field_def):
    rtype = await make(db, settings, fields)
    await add(db, settings, rtype, {"title": "One", "sku": "AB"})

    with pytest.raises(SchemaChangeRefused) as excinfo:
        await apply_fields(db, settings, rtype, [fields[0], tightened(field_def, min_length=5)])

    assert excinfo.value.report.failing == 1
    assert excinfo.value.status_code == 409
    # Nothing was written — not even the version bump §8.6 describes first.
    assert (rtype.schema_version, rtype.version) == (1, 1)
    assert rtype.fields[1]["constraints"] == {}


async def test_force_applies_the_change_and_marks_the_failing_record(
    db, settings, fields, field_def
):
    """§8.2/§8.3: forcing applies and *marks*; it never mutates the rows. The
    record stays readable, keeps its value, and says which field is invalid."""
    rtype = await make(db, settings, fields)
    record = await add(db, settings, rtype, {"title": "One", "sku": "AB"})

    updated, _ = await apply_fields(
        db, settings, rtype, [fields[0], tightened(field_def, min_length=5)], force=True
    )
    assert updated.schema_version == 2

    view = record_service.read_view(updated, record)
    assert view["data"]["sku"] == "AB"
    assert view["schema_stale"] is True
    assert [item["field"] for item in view["invalid"]] == ["sku"]


async def test_a_valid_record_reads_back_with_an_empty_invalid_list(db, settings, fields):
    rtype = await make(db, settings, fields)
    record = await add(db, settings, rtype, {"title": "One", "sku": "ABCDEF"})
    assert record_service.read_view(rtype, record)["invalid"] == []


async def test_a_type_change_on_an_indexed_field_enqueues_the_rebuild_and_refuses_filters(
    db, settings, field_def
):
    """§8.5: mid-move the rows exist in two tables, so the field is refused as
    a filter — loudly, by name — until the rebuild clears the marker."""
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "text")],
        settings=settings,
    )
    await add(db, settings, rtype, {"price": "12"})

    updated, diff = await apply_fields(db, settings, rtype, [field_def("price", "number")])

    assert set(updated.reindex_pending) == {"price"}
    assert diff.keys(*{c.kind for c in diff.changes}) == ("price",)
    with pytest.raises(QueryError) as caught:
        build_query(updated, list(updated.fields), [Filter("price", FilterOp.GT, 1)])
    assert caught.value.reason == "reindexing"


async def test_a_display_field_change_enqueues_a_whole_type_rebuild(db, settings, fields):
    """Every record's ``display_title`` is denormalised from the pointer
    (§18 Q2), so the marker is the reserved whole-type one."""
    rtype = await make(db, settings, fields, display_field="title")
    await add(db, settings, rtype, {"title": "One"})

    updated, _ = await apply_fields(db, settings, rtype, changes={"display_field": "sku"})
    assert REINDEX_ALL in updated.reindex_pending
    assert updated.display_field == "sku"
    assert updated.schema_version == 1  # the fields did not change


async def test_a_slug_field_change_leaves_the_slugs_already_handed_out_alone(db, settings, fields):
    """Deliberate, and the one place the reindex does *not* recompute: a slug
    is an address. Regenerating them would break every link and could collide
    with a slug taken since."""
    rtype = await make(db, settings, fields, slug_field="title")
    record = await add(db, settings, rtype, {"title": "One", "sku": "ABCDEF"})
    assert record.slug == "one"

    updated, _ = await apply_fields(db, settings, rtype, changes={"slug_field": "sku"})
    assert updated.slug_field == "sku"
    assert record.slug == "one"
    assert REINDEX_ALL not in updated.reindex_pending


async def test_a_stale_expected_version_conflicts_before_anything_is_scanned(
    db, settings, fields, field_def
):
    rtype = await make(db, settings, fields)
    await add(db, settings, rtype, {"title": "One"})
    await apply_fields(db, settings, rtype, [*fields, field_def("stock", "integer", indexed=False)])

    with pytest.raises(Conflict) as excinfo:
        # Deliberately the *stale* version (1), not ``rtype.version`` (now 2).
        await schema_change.apply(
            db, rtype, fields_raw=fields, expected_version=1, settings=settings
        )
    assert excinfo.value.current.version == 2


async def test_rollback_writes_an_earlier_revision_back_through_the_pipeline(
    db, settings, fields, field_def
):
    rtype = await make(db, settings, fields)
    await add(db, settings, rtype, {"title": "One"})
    await apply_fields(db, settings, rtype, [*fields, field_def("stock", "integer", indexed=False)])
    assert [f["key"] for f in rtype.fields] == ["title", "sku", "stock"]

    updated, diff = await rollback_to(db, settings, rtype, 1)
    assert [f["key"] for f in updated.fields] == ["title", "sku"]
    # Undoing an addition is a *deletion*, classified like any other.
    assert diff.kind.value == "destructive"
    assert updated.schema_version == 3


async def test_rollback_is_refused_when_it_would_invalidate_records(db, settings, field_def):
    """The whole point of routing it through ``apply`` (§8.6): an undo is not
    privileged. Going back to a schema the current records do not satisfy is
    refused with the same report as any other restrictive change."""
    required = {**field_def("sku", "text", indexed=False), "required": True}
    optional = field_def("sku", "text", indexed=False)
    rtype = await type_service.create_type(
        db, key="product", label="Product", fields_raw=[required], settings=settings
    )
    await apply_fields(db, settings, rtype, [optional])
    await add(db, settings, rtype, {})

    with pytest.raises(SchemaChangeRefused) as excinfo:
        await rollback_to(db, settings, rtype, 1)
    assert excinfo.value.report.failing == 1
    assert rtype.fields[0]["required"] is False


async def test_rollback_to_a_version_that_does_not_exist_is_a_404(db, settings, fields):
    rtype = await make(db, settings, fields)
    with pytest.raises(NotFound):
        await rollback_to(db, settings, rtype, 99)
