"""A uuid that exists in two table sets, and the two layers that answer it.

Phase 5 §6.4 says a ``uuid`` is globally unique across collections and left it
to ``uuid4``. A QA pass found the importer was enough to break that on purpose
— it keeps a file's uuid verbatim (§2), so exporting a global type and
importing it into a collection type planted a duplicate deterministically —
and that everything resolving a record by uuid then acted on the wrong row.

So there are two layers, and this file tests both:

* **The data**: the importer refuses to create a record whose uuid another
  table set holds (``services._uuids``). That is the half the importer can
  enforce, and ``test_import_uuid_across_sets.py`` covers it.
* **The behaviour, regardless of the data**: every lookup keys on
  ``(target_type_id, target_uuid)`` and takes its table set from the declared
  type. Which is what this file asserts — and it therefore has to plant the
  collision **beneath** the importer, with a direct ``UPDATE``, exactly as a
  hand-written row or a restore from an old backup would.

The graph is the one the QA report used: a global ``hall``, a global ``deal``
with a ``spot`` relation to it, and a ``gig`` in the ``events`` collection
whose uuid is made to equal the hall's.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_records.models import GLOBAL
from sqlalchemy import select
from sqlalchemy import update as sa_update

from tests.app_harness import ADMIN, roles
from tests.collections_harness import EVENTS
from tests.relation_helpers import field, make_record, make_type

API = "/api/records/types"


async def _collide(db_state, gig_uuid: str, hall_uuid: str) -> None:
    """Give the collection's record the global record's uuid.

    A core ``UPDATE`` and not the API: the importer refuses this now, which is
    the point of the other half of the fix. Nothing else has to move — a ref
    row names its *target*, and the gig is nobody's target — so this is the
    smallest possible statement of "the collision exists".
    """
    async with db_state.session_factory() as session:
        cls = EVENTS.record
        await session.execute(sa_update(cls).where(cls.uuid == gig_uuid).values(uuid=hall_uuid))
        await session.commit()


@pytest_asyncio.fixture
async def collided(client):
    """``(hall, deal, on_delete setter)`` with the gig sharing the hall's uuid.

    The relation's ``on_delete`` is chosen per test, so the graph is built by
    the returned callable rather than by the fixture.
    """

    async def build(on_delete: str = "restrict"):
        await make_type(client, "hall", [field("name", "text")])
        await make_type(
            client,
            "deal",
            [
                field("name", "text"),
                field("spot", "relation", target_type="hall", on_delete=on_delete),
            ],
        )
        await make_type(client, "gig", [field("name", "text")], collection="events")
        hall = await make_record(client, "hall", {"name": "Barbican"})
        deal = await make_record(
            client, "deal", {"name": "D1", "spot": {"type": "hall", "uuid": hall["uuid"]}}
        )
        gig = await make_record(client, "gig", {"name": "Clash"})
        await _collide(client.db_state, gig["uuid"], hall["uuid"])
        return hall, deal

    return build


async def test_the_collision_is_really_there(collided, client):
    """Both records answer to the same uuid, each under its own type."""
    hall, _ = await collided()
    gig = await client.get(f"{API}/gig/records/{hall['uuid']}", headers=roles(ADMIN))
    assert gig.status_code == 200, gig.text
    assert gig.json()["data"]["name"] == "Clash"
    still = await client.get(f"{API}/hall/records/{hall['uuid']}", headers=roles(ADMIN))
    assert still.json()["data"]["name"] == "Barbican"


async def test_referrers_of_the_collection_record_are_its_own(collided, client):
    """The deal points at the *hall*. ``referrers`` used to key on the uuid
    alone, so the gig inherited it."""
    hall, _ = await collided()
    refs = await client.get(f"{API}/gig/records/{hall['uuid']}/referrers", headers=roles(ADMIN))
    assert refs.status_code == 200, refs.text
    assert refs.json()["total"] == 0
    assert refs.json()["items"] == []

    mine = await client.get(f"{API}/hall/records/{hall['uuid']}/referrers", headers=roles(ADMIN))
    assert mine.json()["total"] == 1


async def test_restrict_does_not_block_a_delete_nothing_references(collided, client):
    hall, _ = await collided("restrict")
    gone = await client.delete(f"{API}/gig/records/{hall['uuid']}", headers=roles(ADMIN))
    assert gone.status_code == 204, gone.text
    # And the hall, which *is* referenced, is still refused.
    kept = await client.delete(f"{API}/hall/records/{hall['uuid']}", headers=roles(ADMIN))
    assert kept.status_code == 409, kept.text


async def test_cascade_does_not_trash_an_unrelated_record(collided, client):
    hall, deal = await collided("cascade")
    gone = await client.delete(f"{API}/gig/records/{hall['uuid']}", headers=roles(ADMIN))
    assert gone.status_code == 204, gone.text
    survivor = await client.get(f"{API}/deal/records/{deal['uuid']}", headers=roles(ADMIN))
    assert survivor.status_code == 200, survivor.text
    assert survivor.json()["version"] == 1


async def test_set_null_does_not_blank_an_unrelated_record(collided, client):
    hall, deal = await collided("set_null")
    gone = await client.delete(f"{API}/gig/records/{hall['uuid']}", headers=roles(ADMIN))
    assert gone.status_code == 204, gone.text
    after = await client.get(f"{API}/deal/records/{deal['uuid']}", headers=roles(ADMIN))
    assert after.json()["data"]["spot"] == {"type": "hall", "uuid": hall["uuid"]}
    assert after.json()["version"] == 1, "the referrer was rewritten by somebody else's delete"


async def test_a_relation_write_to_the_global_record_is_still_accepted(collided, client):
    """``check_targets`` merged a uuid → type map across every table set, so
    the last set asked won and the hall stopped being a hall."""
    hall, _ = await collided()
    made = await client.post(
        f"{API}/deal/records",
        json={"data": {"name": "D2", "spot": {"type": "hall", "uuid": hall["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert made.status_code == 201, made.text


async def test_a_relation_write_to_a_uuid_of_the_wrong_type_is_still_refused(collided, client):
    """The other half of the same predicate: pointing a ``hall`` field at a
    record that is not a hall is still the 422 it always was, and the message
    is still the "is not a" one rather than "no record with uuid"."""
    await collided()
    await make_type(client, "other", [field("name", "text")])
    other = await make_record(client, "other", {"name": "O"})
    refused = await client.post(
        f"{API}/deal/records",
        json={"data": {"name": "D3", "spot": {"type": "hall", "uuid": other["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 422, refused.text
    assert "is not a 'hall'" in refused.text


async def test_expand_and_the_public_read_were_already_right(collided, client):
    """Both predicate on the declared target type inside that type's own set,
    which is the shape the other fixes were brought up to."""
    _, deal = await collided()
    read = await client.get(f"{API}/deal/records/{deal['uuid']}?expand=spot", headers=roles(ADMIN))
    assert read.json()["expanded"]["spot"][0]["display_title"] == "Barbican"


@pytest.mark.parametrize("key", ["hall", "gig"])
async def test_each_type_reads_its_own_row_by_uuid(collided, client, key):
    hall, _ = await collided()
    body = await client.get(f"{API}/{key}/records/{hall['uuid']}", headers=roles(ADMIN))
    assert body.json()["display_title"] == {"hall": "Barbican", "gig": "Clash"}[key]


async def test_the_gigs_row_is_in_the_collections_table(collided, client):
    """Guards the planting itself: if the ``UPDATE`` stopped landing, every
    assertion above would pass for the wrong reason."""
    hall, _ = await collided()
    async with client.db_state.session_factory() as session:
        stmt = select(EVENTS.record.id).where(EVENTS.record.uuid == hall["uuid"])
        found = (await session.execute(stmt)).scalars().all()
        shared = select(GLOBAL.record.id).where(GLOBAL.record.uuid == hall["uuid"])
        globals_ = (await session.execute(shared)).scalars().all()
    assert len(found) == 1, "the gig row is not in the collection's table"
    assert len(globals_) == 1, "the hall row is not in the shared table"
