"""``sm_records.contracts.dated``: who may read what, and the type and field listings."""

from __future__ import annotations

import pytest
from sm_records.contracts.dated import (
    DatedCaller,
    dated_field_kind,
    dated_types,
)
from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordStatus
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service

from tests.contracts.dated_support import (  # noqa: F401
    FIELDS,
    HI,
    HI_T,
    LO,
    LO_T,
    SETTINGS,
    VIEW,
    add,
    caller,
    make_type,
    read,
)
from tests.support.app_harness import field


async def test_anonymous_needs_public_type(db):
    private = await make_type(db, "private_t", is_public=False)
    public = await make_type(db, "public_t", is_public=True)
    await add(db, private, "secret", due="2026-07-05")
    await add(db, public, "open", due="2026-07-05")
    assert (await read(db, "private_t", who=None, locale="en")).hits == []
    assert [h.display_title for h in (await read(db, "public_t", who=None, locale="en")).hits] == [
        "open"
    ]
    assert [h.display_title for h in (await read(db, "private_t", who=caller())).hits] == ["secret"]


async def test_anonymous_never_sees_drafts_of_a_public_type(db):
    public = await make_type(db, "public_t", is_public=True)
    await add(db, public, "draft", due="2026-07-05", status=RecordStatus.DRAFT)
    assert (await read(db, "public_t", who=None, locale="en")).hits == []


async def test_view_permission_required(db):
    rtype = await make_type(db)
    await add(db, rtype, "r", due="2026-07-05")
    assert (await read(db, who=caller(perms=()))).hits == []
    assert (await read(db, who=caller(perms=("records.edit",)))).hits == []
    assert len((await read(db, who=caller())).hits) == 1


async def test_allowed_roles_narrowing_and_type_grant(db):
    rtype = await make_type(db, allowed_roles=["editor"])
    await add(db, rtype, "r", due="2026-07-05")
    assert len((await read(db, who=caller("editor"))).hits) == 1
    assert (await read(db, who=caller("viewer"))).hits == []
    # a per-type grant widens the narrowing, for a caller with no role of the list
    assert len((await read(db, who=caller("viewer", granted=("deadlines",)))).hits) == 1
    # the wildcard rule: an admin role not named in allowed_roles gets nothing
    admin = DatedCaller(roles=("admin",), permissions=frozenset({"*"}), role_map={"admin": ["*"]})
    assert (await read(db, who=admin)).hits == []
    named = await make_type(db, "named_t", allowed_roles=["admin"])
    await add(db, named, "r", due="2026-07-05")
    assert len((await read(db, "named_t", who=admin)).hits) == 1


async def test_dated_types_lists_readable_indexed_fields_only(db):
    await make_type(db, "open_t")
    await make_type(db, "narrow_t", allowed_roles=["editor"])
    await type_service.create_type(
        db, key="nodates", label="n", fields_raw=[field("a", "text")], settings=SETTINGS
    )
    found = await dated_types(db, tenant_id="default", caller=caller("viewer"))
    assert [t.key for t in found] == ["open_t"]  # narrow_t is not readable; nodates has no date
    (info,) = found
    assert info.fields == [
        ("due", "Due", "date"),
        ("at", "At", "datetime"),
        ("until", "Until", "date"),
        ("ends", "Ends", "datetime"),
    ]
    wide = await dated_types(db, tenant_id="default", caller=caller("editor"))
    assert sorted(t.key for t in wide) == ["narrow_t", "open_t"]
    assert await dated_types(db, tenant_id="default", caller=caller(perms=())) == []


async def test_dated_field_kind(db):
    await make_type(db, "private_t")
    await make_type(db, "public_t", is_public=True)
    ask = {"tenant_id": "default", "field": "due"}
    assert await dated_field_kind(db, type_key="private_t", caller=caller(), **ask) == "date"
    assert (
        await dated_field_kind(
            db, type_key="private_t", caller=caller(), tenant_id="default", field="at"
        )
        == "datetime"
    )
    # no such type, one the caller may not read, no such or non-date field: nothing is said
    assert await dated_field_kind(db, type_key="nope", caller=caller(), **ask) is None
    assert await dated_field_kind(db, type_key="private_t", caller=None, **ask) is None
    assert await dated_field_kind(db, type_key="public_t", caller=None, **ask) == "date"
    assert await dated_field_kind(db, type_key="private_t", caller=caller(perms=()), **ask) is None
    assert (
        await dated_field_kind(
            db, type_key="private_t", caller=caller(), tenant_id="default", field="title"
        )
        is None
    )


async def test_the_public_must_name_a_locale_the_site_publishes(db):
    public = await make_type(db, "public_t", is_public=True)
    await add(db, public, "open", due="2026-07-05")
    for bad in (None, "xx"):
        with pytest.raises(ValueError):
            await read(db, "public_t", who=None, locale=bad, settings=RecordsSettings())
    # a language the type does not use is simply empty; the signed-in read needs none
    both = RecordsSettings(content_locales=("en", "de"))
    assert (await read(db, "public_t", who=None, locale="de", settings=both)).hits == []


async def test_a_record_in_a_language_the_site_does_not_publish_is_absent_anonymously(db):
    both = RecordsSettings(content_locales=("en", "de"))
    only_en = RecordsSettings(content_locales=("en",))
    rtype = await make_type(db, "public_t", is_public=True, translatable=True)
    for locale, title in (("en", "hello"), ("de", "hallo")):
        await record_service.create_record(
            db,
            rtype,
            data={"title": title, "due": "2026-07-05"},
            settings=both,
            status=RecordStatus.PUBLISHED,
            locale=locale,
        )
    ok = await read(db, "public_t", who=None, locale="de", settings=both)
    assert [h.display_title for h in ok.hits] == ["hallo"]
    with pytest.raises(ValueError):  # the site stopped publishing German: not even asked for
        await read(db, "public_t", who=None, locale="de", settings=only_en)


async def test_a_record_with_a_stored_invalid_mark_is_never_returned(db):
    from sm_records.models import Record
    from sm_records.records.services._common import utcnow
    from sqlalchemy import update

    rtype = await make_type(db, "public_t", is_public=True)
    bad = await add(db, rtype, "invalid", due="2026-07-05")
    await add(db, rtype, "fine", due="2026-07-06")
    await db.execute(update(Record).where(Record.id == bad.id).values(invalid_since=utcnow()))
    await db.flush()
    assert [h.display_title for h in (await read(db, "public_t", who=None, locale="en")).hits] == [
        "fine"
    ]
    assert [h.display_title for h in (await read(db, "public_t")).hits] == ["fine"]
