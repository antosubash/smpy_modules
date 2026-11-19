"""An event can only use a registration form its editor may read (PR 9, security review)."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import registry
from sm_events.contracts.extensions import SourceViewer
from sm_events.core.errors_registration import UnknownRegistrationTarget
from sm_events.registration.access import target_readable
from sm_events.web.services.events_out import registration_out

from tests.support.access import seed_calendars
from tests.support.providers import (
    OPEN_TARGET,
    PROVIDER_ID,
    SECRET_TARGET,
    install_provider,
    restricted,
)
from tests.support.writes import LOCALES, OWNER_P, make

ALICE = SourceViewer("alice", (), frozenset({"events.edit"}), None)
BOB = SourceViewer("bob", (), frozenset({"events.edit"}), None)


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, restricted())
    yield
    registry.reset_registry()


def reg(target, **more):
    return {"mode": "builtin", "provider": PROVIDER_ID, "target": target, **more}


@pytest.fixture
async def cal(db):
    return (await seed_calendars(db))["I"]


async def _patch(db, event, who, **body):
    from sm_events.content.events_write import update_event
    from sm_events.web.schemas.events_in import EventPatch

    await update_event(
        db, OWNER_P, event.id, EventPatch(expected_revision=event.revision, **body),
        locales=LOCALES, viewer=who,
    )  # fmt: skip
    await db.refresh(event)


async def test_an_editor_without_rights_is_refused_like_a_missing_form(db, cal):
    errors = []
    for target in (SECRET_TARGET, "does-not-exist"):
        with pytest.raises(UnknownRegistrationTarget) as caught:
            await make(db, OWNER_P, cal, registration=reg(target), viewer=BOB)
        errors.append((caught.value.status_code, caught.value.code, caught.value.detail))
    assert errors[0] == errors[1]
    assert "Label of" not in str(errors) and SECRET_TARGET not in str(errors)
    ok = await make(db, OWNER_P, cal, registration=reg(SECRET_TARGET), viewer=ALICE)
    assert ok.registration_target == SECRET_TARGET
    open_ = await make(db, OWNER_P, cal, registration=reg(OPEN_TARGET), viewer=BOB)
    assert open_.registration_target == OPEN_TARGET


async def test_no_caller_fails_closed(db, cal):
    with pytest.raises(UnknownRegistrationTarget):
        await make(db, OWNER_P, cal, registration=reg(OPEN_TARGET), viewer=None)
    event = await make(db, OWNER_P, cal)
    from sm_events.core.errors import NotFound  # noqa: F401

    with pytest.raises(UnknownRegistrationTarget):
        await _patch(db, event, None, registration=reg(OPEN_TARGET))


async def test_the_placeholder_is_what_an_editor_without_rights_reads(db, cal):
    event = await make(db, OWNER_P, cal, registration=reg(SECRET_TARGET, capacity=3), viewer=ALICE)
    assert await target_readable(db, event, ALICE) is True
    assert await target_readable(db, event, BOB) is False
    assert await target_readable(db, event, None) is False
    seen = registration_out(event, readable=False)
    assert (seen.target, seen.target_hidden, seen.capacity) == (None, True, 3)
    assert "secret" not in seen.model_dump_json()
    shown = registration_out(event, readable=True)
    assert (shown.target, shown.target_hidden) == (SECRET_TARGET, False)


async def test_their_save_leaves_the_form_untouched_and_cannot_change_it(db, cal):
    event = await make(db, OWNER_P, cal, registration=reg(SECRET_TARGET, capacity=3), viewer=ALICE)
    # the editor's form sends what it was shown: no target
    await _patch(
        db, event, BOB,
        registration={"mode": "builtin", "capacity": 9, "show_seats": True},
    )  # fmt: skip
    assert (event.registration_provider, event.registration_target) == (PROVIDER_ID, SECRET_TARGET)
    assert event.registration_capacity == 9 and event.registration_show_seats is True
    for body in (
        {"mode": "none"},
        reg(OPEN_TARGET),  # a form they may use, but they cannot swap a hidden one
        {"mode": "external", "url": "https://x.example/r"},
    ):
        with pytest.raises(UnknownRegistrationTarget):
            await _patch(db, event, BOB, registration=body)
        await db.refresh(event)
    assert event.registration_target == SECRET_TARGET
    # the stored target sent back as is, by someone who cannot read it, is not a change of form
    await _patch(db, event, BOB, registration=reg(SECRET_TARGET, capacity=11))
    assert event.registration_capacity == 11 and event.registration_target == SECRET_TARGET
    await _patch(db, event, ALICE, registration={"mode": "none"})  # alice may
    assert event.registration_mode == "none"
