"""``/api/records/registration-forms``: pick a form for an event, or make one."""

from __future__ import annotations

import pytest

from tests.support.app_harness import ADMIN, roles
from tests.support.harness_auth import ROLE_EDITOR, ROLE_VIEWER
from tests.support.public_submissions_support import create
from tests.support.registration_http import TYPE, reg_config, reg_fields

pytestmark = pytest.mark.usefixtures("reg_site")
URL = "/api/records/registration-forms"


async def test_create_and_dedupe(reg_site):
    first = await reg_site.post(URL, headers=roles(ADMIN))
    assert (first.status_code, first.json()) == (201, {"key": "event_registrations_2"})
    second = await reg_site.post(URL, headers=roles(ADMIN))
    assert second.json() == {"key": "event_registrations_3"}
    made = await reg_site.get("/api/records/types/event_registrations_2", headers=roles(ADMIN))
    config = made.json()["public_submissions"]
    assert config["kind"] == "registration" and config["double_opt_in"] is True
    assert config["enabled"] is True and config["pending_hold_hours"] == 24
    # a fresh tenant gets the unsuffixed key
    from sm_records.records.services import types as type_service  # noqa: F401


async def test_needs_manage_types(reg_site):
    for who in (roles(ROLE_VIEWER), roles(ROLE_EDITOR), {}):
        got = await reg_site.post(URL, headers=who)
        assert got.status_code in (401, 403), who


async def test_list_shows_registration_types_the_caller_may_view(reg_site):
    await create(reg_site, "contact")
    made = await create(
        reg_site,
        "private_regs",
        fields=reg_fields(),
        config=reg_config(),
        allowed_roles=[ROLE_EDITOR],
    )
    assert made.status_code == 201, made.text
    seen = (await reg_site.get(URL, headers=roles(ROLE_EDITOR))).json()
    assert [row["key"] for row in seen] == ["event_registrations", "private_regs"]
    row = seen[0]
    assert set(row) == {"key", "label", "enabled", "attendees_url"}
    assert row["enabled"] is True and row["attendees_url"] == f"/admin/records/{TYPE}"
    viewer = (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()
    assert [r["key"] for r in viewer] == ["event_registrations"]  # the editor-only one is hidden
    assert (await reg_site.get(URL)).status_code in (401, 403)
