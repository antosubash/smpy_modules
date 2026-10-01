"""Re-deriving the stored mark — the ``rescan`` behind "Check records".

A scan of the schema records are *stored* against is the only thing that can
notice a payload that changed outside the module, in either direction: a
record somebody fixed in the database is still marked, and one somebody broke
there is not. It is also the only preview that writes, which is what the
deferred path here is about — a job nobody commits rolls back silently, and
the report on screen would then describe a worklist the database never
learned about.

What writes the mark in the first place is ``test_invalid_flag``; the counts
that read it back are here because they are what an operator sees once a scan
has run.
"""

from __future__ import annotations

from types import SimpleNamespace

from simple_module_core.health import HealthStatus
from sm_records.health import stale_reindex_check
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles
from tests.invalid_support import (
    TYPES,
    clear_mark,
    edit_payload,
    force_required_sku,
    read,
    rescan,
    type_with,
)


async def test_a_rescan_clears_a_fixed_record_and_marks_a_newly_broken_one(client):
    """Both directions in one pass. The two payloads are swapped underneath
    the API, which is the case the derived badge could always see and the
    stored one could not until something re-derived it."""
    state = await type_with(client, {"name": "Widget"}, {"name": "Gadget", "sku": "G-1"})
    saved = await force_required_sku(client, state["type"])
    was_broken, was_fine = state["uuids"]
    assert (await read(client, was_broken))["invalid_since"] is not None
    assert (await read(client, was_fine))["invalid_since"] is None

    await edit_payload(client, was_broken, {"name": "Widget", "sku": "W-1"})
    await edit_payload(client, was_fine, {"name": "Gadget"})

    report = await rescan(client, saved["fields"])
    assert report["checked"] == 2 and report["failing"] == 1
    assert [entry["uuid"] for entry in report["sample"]] == [was_fine]
    assert (await read(client, was_broken))["invalid_since"] is None
    assert (await read(client, was_fine))["invalid_since"] is not None


async def test_a_rescan_does_not_move_a_mark_that_is_still_true(client):
    """ "Since" means since — a record that was already failing keeps the
    instant it first did, however many times it is checked again."""
    state = await type_with(client, {"name": "Widget"})
    saved = await force_required_sku(client, state["type"])
    first = (await read(client, state["uuids"][0]))["invalid_since"]

    await rescan(client, saved["fields"])
    assert (await read(client, state["uuids"][0]))["invalid_since"] == first


async def test_a_deferred_rescan_commits_its_marks(client):
    """Above ``preview_sync_limit`` the scan runs after the response, on a
    session of its own — and a session nobody commits rolls back at the end of
    the ``async with``. ``services/preview_runner.py`` is what commits it, and
    this is the difference between a report on screen and a worklist in the
    database.
    """
    state = await type_with(client, {"name": "Widget"}, {"name": "Gadget", "sku": "G-1"})
    saved = await force_required_sku(client, state["type"])
    # Erased behind the API, so only the deferred scan can put it back. The
    # payload is untouched, so the record still fails the stored schema.
    await clear_mark(client, state["uuids"][0])
    assert (await read(client, state["uuids"][0]))["invalid_since"] is None

    client.app.state.sm_records.settings = RecordsSettings(preview_sync_limit=1)
    started = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": saved["fields"], "rescan": True},
        headers=roles(ADMIN),
    )
    assert started.status_code == 202, started.text
    job = (
        await client.get(
            f"{TYPES}/product/schema/preview/{started.json()['job']}", headers=roles(ADMIN)
        )
    ).json()
    assert job["status"] == "done", job
    assert job["preview"]["report"]["failing"] == 1
    assert (await read(client, state["uuids"][0]))["invalid_since"] is not None


async def test_a_draft_preview_marks_nothing(client):
    """ "Preview changes" scans a field list that may never be saved. Marking
    from it would flag records against a schema nobody applied — and would
    make the button that says it writes nothing a liar."""
    state = await type_with(client, {"name": "Widget"})
    created = state["type"]

    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": [created["fields"][0], {**created["fields"][1], "required": True}]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    assert resp.json()["report"]["failing"] == 1
    assert (await read(client, state["uuids"][0]))["invalid_since"] is None


async def test_the_type_read_counts_the_marked_records(client):
    """The hub row's number, and the one the list link behind it produces."""
    state = await type_with(client, {"name": "Widget"}, {"name": "Gadget", "sku": "G-1"})
    await force_required_sku(client, state["type"])

    read = (await client.get(f"{TYPES}/product", headers=roles(ADMIN))).json()
    assert read["record_count"] == 2
    assert read["invalid_record_count"] == 1


async def test_the_count_ignores_the_trash(client):
    """It is the number beside a link to the *list*, and a list does not show
    trashed records — a count that included them would send an operator to a
    screen with fewer rows on it than the badge promised."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    await client.delete(f"{TYPES}/product/records/{state['uuids'][0]}", headers=roles(ADMIN))

    read = (await client.get(f"{TYPES}/product", headers=roles(ADMIN))).json()
    assert read["invalid_record_count"] == 0


async def test_the_health_check_reports_the_count(client):
    """Forcing a change is a decision somebody made; forgetting about the
    records it left behind is what the detail line is against."""
    state = await type_with(client, {"name": "Widget"})
    module = SimpleNamespace(db=client.db_state, settings=RecordsSettings())
    assert (await stale_reindex_check(module).check()).status is HealthStatus.HEALTHY

    await force_required_sku(client, state["type"])
    result = await stale_reindex_check(module).check()
    assert result.status is HealthStatus.DEGRADED
    assert "invalid_records: 1" in result.detail
