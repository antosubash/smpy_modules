"""``?expand=`` lines up with the payload it is rendered beside.

An expansion resolves only against the target type the field declares, keeps
a slot for every entry the payload holds, and expands a relation nobody filled
in to nothing rather than to one phantom ``dangling`` reference.
"""

from __future__ import annotations

import pytest
from sm_records.models import Record
from sm_records.schema.compile import PayloadValidationError
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services.expand import expand
from sqlalchemy import select

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.field_builders import rel, text
from tests.relation_helpers import field, library, make_record, make_type

API = "/api/records"


# ---------------------------------------------------------------------------
# what ``?expand=`` resolves, and what it lines up with
# ---------------------------------------------------------------------------


async def _retype_payload(db_state, uuid: str, data: dict) -> None:
    """Write a payload the current write path would refuse — the rows §9 says
    exist from before ``check_targets``/``_check_ref_list`` did."""
    async with db_state.session_factory() as session:
        row = (await session.execute(select(Record).where(Record.uuid == uuid))).scalars().first()
        row.data = data
        session.add(row)
        await session.commit()


async def test_a_ref_naming_another_type_than_the_field_declares_is_dangling(client, records_app):
    _app, db_state = records_app
    await make_type(client, "secret", [field("name", "text")], allowed_roles=[ROLE_EDITOR])
    hidden = await make_record(client, "secret", {"name": "Top Secret"}, actor=ROLE_EDITOR)
    await library(client)
    author = await make_record(client, "author", {"name": "Visible"})
    book = await make_record(
        client, "book", {"name": "B", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await _retype_payload(
        db_state, book["uuid"], {"name": "B", "author": {"type": "secret", "uuid": hidden["uuid"]}}
    )

    got = await client.get(
        f"{API}/types/book/records/{book['uuid']}?expand=author", headers=roles(ROLE_VIEWER)
    )
    ref = got.json()["expanded"]["author"][0]
    assert ref["dangling"] is True
    assert ref["display_title"] is None
    assert "Top Secret" not in got.text


async def test_a_null_inside_a_to_many_relation_is_refused_on_write(client):
    await library(client, many=True)
    author = await make_record(client, "author", {"name": "One"})
    resp = await client.post(
        f"{API}/types/book/records",
        json={
            "data": {
                "name": "B",
                "author": [{"type": "author", "uuid": author["uuid"]}, None],
            }
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "author"
    assert "entry 1" in resp.json()["errors"][0]["message"]


async def test_a_stored_null_keeps_its_slot_in_the_expansion(client, records_app):
    """The write path refuses one now; a row that already holds one must still
    render, and ``expanded[i]`` must still be ``data[i]``."""
    _app, db_state = records_app
    await library(client, many=True)
    one = await make_record(client, "author", {"name": "One"})
    two = await make_record(client, "author", {"name": "Two"})
    book = await make_record(
        client, "book", {"name": "B", "author": [{"type": "author", "uuid": one["uuid"]}]}
    )
    await _retype_payload(
        db_state,
        book["uuid"],
        {
            "name": "B",
            "author": [
                {"type": "author", "uuid": one["uuid"]},
                None,
                {"type": "author", "uuid": two["uuid"]},
            ],
        },
    )

    got = await client.get(
        f"{API}/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    expanded = got.json()["expanded"]["author"]
    assert len(expanded) == len(got.json()["data"]["author"]) == 3
    assert [ref["display_title"] for ref in expanded] == ["One", None, "Two"]
    assert expanded[1]["dangling"] is True


def test_the_compiled_validator_names_the_offending_entry():
    from sm_records.schema._builders import annotation_for
    from sm_records.schema.compile import build_model, validate_payload
    from sm_records.schema.fields import validate_fields

    defs = validate_fields(
        [field("author", "relation", target_type="author", many=True)], on_save=True
    )
    assert annotation_for(defs[0], required=False) is not None
    model = build_model("book", 1, defs)
    with pytest.raises(PayloadValidationError) as exc:
        validate_payload(model, {"author": ["not-an-object"]})
    assert exc.value.errors[0]["field"] == "author"


# ---------------------------------------------------------------------------
# an empty relation expands to nothing
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
