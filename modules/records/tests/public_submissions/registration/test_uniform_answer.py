"""The answer to a submit never depends on whether the address already holds a registration, except
where a *new* record would take a seat and events is busy (see docs/registration.md).

The table: address state (new / pending / registered / cancelled), form mode (single / double
opt-in) and seats (free / full / busy): each cell answers like the unknown-address cell, or the
difference is the one listed in docs/registration.md."""

from __future__ import annotations

import pytest
from sm_events.contracts import registration as contract
from sm_events.core.errors_registration import SeatsBusy
from sm_records.public_submissions.registration import mail as reg_mail

from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    TYPE,
    confirm_record,
    load_registration,
    reg_config,
    register,
    regs,
    seed_event,
)

pytestmark = pytest.mark.usefixtures("reg_site")
ME = "ada@example.org"
CONSENT = {"required": True, "text": {"en": "ok"}}


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def mode(site, name):
    config = reg_config(double_opt_in=name == "double", consent=CONSENT)
    resp = await update_type(site, TYPE, public_submissions=config)
    assert resp.status_code == 200, resp.text


async def submit(site, event, address, token=None):
    if token is None:
        token = (await load_registration(site, event)).json()["definition"]["token"]
    return await register(site, address, event=event, consent=True, token=token)


async def make_state(site, event, state):
    """Put ``ME`` into ``state`` (built on a double opt-in form, so every state is reachable)."""
    await mode(site, "double")
    if state == "new":
        return
    assert (await submit(site, event, ME)).status_code == 202
    record = next(r for r in await regs(site) if r["data"]["sm_email"] == ME)
    if state in ("registered", "cancelled"):
        assert (await confirm_record(site, record)).status_code == 200
    if state == "cancelled":
        from tests.support.app_harness import ADMIN, roles
        from tests.support.registration_http import record_url

        done = await site.post(
            record_url(record["uuid"], "/submission/cancel"), headers=roles(ADMIN)
        )
        assert done.status_code == 200


async def fill(site, event, taken):
    """Other registrants until the capacity of 3 is used (``taken`` seats are already held)."""
    for n in range(3 - taken):
        assert (await submit(site, event, f"other{n}@example.org")).status_code == 202
        record = next(
            r for r in await regs(site) if r["data"]["sm_email"] == f"other{n}@example.org"
        )
        assert (await confirm_record(site, record)).status_code == 200


def answer(resp):
    return resp.status_code, resp.json()


@pytest.mark.parametrize("state", ["new", "pending", "registered", "cancelled"])
@pytest.mark.parametrize("form", ["single", "double"])
@pytest.mark.parametrize("seats", ["free", "full", "busy"])
async def test_the_answer_does_not_depend_on_who_is_asking(
    reg_site, monkeypatch, state, form, seats
):
    event = await seed_event(
        reg_site.db_state, uid=f"u-{state}-{form}-{seats}@x", registration_capacity=3
    )
    await make_state(reg_site, event, state)
    early = (await load_registration(reg_site, event)).json()["definition"]["token"]
    if seats == "full":
        await fill(reg_site, event, 1 if state == "registered" else 0)
    await mode(reg_site, form)
    if seats == "busy":

        async def busy(*_a, **_k):
            raise SeatsBusy

        monkeypatch.setattr(contract, "admit", busy)
    got = answer(await submit(reg_site, event, ME, early))

    if seats == "free":
        assert got == (202, {"ok": True})
    elif seats == "full":
        assert got[0] == 409 and got[1]["code"] == "registration_full"  # for everyone alike
    else:
        creates_a_seat = form == "single" and state in ("new", "cancelled")
        if creates_a_seat:
            # The one documented difference: only a NEW record would take a seat, so only there can
            # busy surface; an address that already holds a live registration answers 202.
            assert got[0] == 409 and got[1] == {"detail": "the seats are busy; try again"}
        else:
            assert got == (202, {"ok": True})
