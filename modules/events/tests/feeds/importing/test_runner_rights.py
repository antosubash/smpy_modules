"""The importer's rights are asked again at the start of every apply slice."""

from __future__ import annotations

import pytest
from simple_module_core.resources import ResourcePrincipal
from sm_events.core import constants
from sm_events.core.access.offline import offline_principal
from sm_events.feeds.importing import launch as launch_module

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import PUBLISHER, queue, read, run, stage
from tests.support.tokens import install_directory, install_members

SLICE = {"clock": None}


def _expired():
    ticks = iter(range(10**6))
    return lambda: next(ticks) * 1000.0


class Importer:
    """What the runner asks at the top of a slice: the importer's permissions now, or ``None``."""

    def __init__(self, *perms: str | None) -> None:
        self.answer: frozenset[str] | None = None if perms == (None,) else frozenset(perms)
        self.asked: list[tuple[str, str]] = []

    async def __call__(self, tenant_id: str, user_id: str):
        self.asked.append((tenant_id, user_id))
        return None if self.answer is None else ResourcePrincipal(user_id, self.answer)


async def test_rights_unchanged_are_unaffected(events_app):
    _app, state = events_app
    importer = Importer("events.view", "events.manage")
    _cal, import_id = await stage(state, corpus.simple(3))
    await run(state, import_id)
    await queue(state, import_id)
    assert await run(state, import_id, importer=importer) == "done"
    imp, _items, events = await read(state, import_id)
    assert (imp.created, imp.skipped, len(events)) == (3, 0, 3)
    assert importer.asked == [("default", "m")]  # once per slice, not per item


async def test_a_role_removed_between_slices_refuses_the_later_items(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 2)
    importer = Importer("events.view", "events.manage")
    _cal, import_id = await stage(state, corpus.simple(5))
    await run(state, import_id)
    await queue(state, import_id)
    expired = _expired()
    assert await run(state, import_id, importer=importer, clock=expired) == "more"
    importer.answer = frozenset({"events.view"})  # lost events.manage after the first slice
    assert await run(state, import_id, importer=importer, clock=expired) == "more"
    assert await run(state, import_id, importer=importer, clock=expired) == "done"
    imp, items, events = await read(state, import_id)
    assert [(i.outcome, i.outcome_code) for i in items] == [
        ("created", None),
        ("created", None),
        ("skipped", "forbidden"),
        ("skipped", "forbidden"),
        ("skipped", "forbidden"),
    ]
    assert (imp.created, imp.skipped, len(events)) == (2, 3, 2)


async def test_the_narrower_of_stored_and_current_rights_wins(events_app):
    """A current answer richer than the stored grants never widens them."""
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(2))
    await run(state, import_id)
    await queue(state, import_id, publish=True, grants=("events.view", "events.manage"))
    rich = Importer(*PUBLISHER)
    assert await run(state, import_id, importer=rich) == "done"
    _imp, _items, events = await read(state, import_id)
    assert {e.status for e in events} == {"draft"}  # publishing was never stored for this import


async def test_a_deactivated_importer_ends_the_import(events_app):
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(3))
    await run(state, import_id)
    await queue(state, import_id)
    assert await run(state, import_id, importer=Importer(None)) == "done"
    imp, items, events = await read(state, import_id)
    assert (imp.status, imp.error_code, imp.source) == ("failed", "importer_gone", None)
    assert all(i.outcome is None for i in items) and events == []  # remaining items untouched
    assert imp.finished_at is not None and imp.lease_owner is None


async def _live(events_app):
    app, state = events_app
    directory = install_directory(app)
    members = {"default": {"m"}}
    install_members(app, members)
    return app, state, directory, members


@pytest.mark.parametrize("how", ["inactive", "roles_unknown"])
async def test_the_real_offline_resolution_stops_the_import(events_app, how, monkeypatch):
    """Through ``launch``'s own check (the user directory and tenant membership), eager."""
    monkeypatch.setattr(launch_module, "celery_eager", lambda: True)
    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 2)
    app, state, directory, _members = await _live(events_app)
    from sm_events.core.tenancy import mode_of  # noqa: F401

    _cal, import_id = await stage(state, corpus.simple(4))
    await run(state, import_id)
    await queue(state, import_id)
    check = launch_module.importer_check(app)
    expired = _expired()
    assert await run(state, import_id, importer=check, clock=expired) == "more"
    if how == "inactive":
        email, name, _ = directory.users["m"]
        directory.users["m"] = (email, name, False)
    else:
        # a single-tenant host skips membership; ask as a tenant the host does not run
        directory.roles["m"] = None
    assert await run(state, import_id, importer=check, clock=expired) == "done"
    imp, items, _events = await read(state, import_id)
    assert (imp.status, imp.error_code) == ("failed", "importer_gone")
    assert [i.outcome for i in items] == ["created", "created", None, None]


async def test_the_check_is_the_offline_principal(events_app):
    app, _state, _directory, _members = await _live(events_app)
    check = launch_module.importer_check(app)
    from sm_events.core.tenancy import tenant_scope

    with tenant_scope("default"):
        who = await check("default", "m")
    assert who is not None and who.has("events.manage")
    assert offline_principal is not None


@pytest.mark.unbound_tenant
async def test_an_importer_removed_from_the_tenant_ends_the_import(monkeypatch):
    """A multi-tenant host: membership is asked every slice, and a removed member is gone."""
    from sm_events.core.tenancy import tenant_scope

    from tests.support.tokens import token_app

    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 2)
    app, state = await token_app(multi=True)
    try:
        members = {"a": {"m"}}
        install_members(app, members)
        _cal, import_id = await stage(state, corpus.simple(4), tenant="a")
        await run(state, import_id, tenant="a")
        await queue(state, import_id, tenant="a")
        check = launch_module.importer_check(app)
        expired = _expired()
        assert await run(state, import_id, tenant="a", importer=check, clock=expired) == "more"
        members["a"].discard("m")
        assert await run(state, import_id, tenant="a", importer=check, clock=expired) == "done"
        imp, items, _events = await read(state, import_id, tenant="a")
        assert (imp.status, imp.error_code) == ("failed", "importer_gone")
        assert [i.outcome for i in items] == ["created", "created", None, None]
        _ = tenant_scope
    finally:
        await state.engine.dispose()
