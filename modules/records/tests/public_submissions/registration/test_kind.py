"""The ``registration`` kind: its system fields, its rules, and the routes that never serve it."""

from __future__ import annotations

import pytest

from tests.support.app_harness import ADMIN, roles
from tests.support.public_submissions_support import create, update
from tests.support.registration_http import TYPE, reg_config, reg_fields, registration_type
from tests.support.submissions_http import SUBMISSIONS

SYSTEM = [
    "sm_email", "sm_name", "sm_event_id", "sm_occurrence_key", "sm_occurrence_start",
    "sm_event_title", "sm_status", "sm_locale", "sm_source_page", "sm_consent_text",
    "sm_consent_at", "sm_confirmed_at", "sm_cancelled_at", "sm_confirm_sent_at", "sm_ip_hash",
    "sm_nonce",
]  # fmt: skip


async def test_kind_fields(site):
    resp = await registration_type(site)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    by_key = {f["key"]: f for f in body["fields"]}
    assert [k for k, f in by_key.items() if f.get("system")] == SYSTEM
    assert by_key["sm_email"]["unique"] is False and by_key["sm_email"]["required"] is True
    assert by_key["sm_email"]["indexed"] is True and by_key["sm_name"]["required"] is True
    for key in ("sm_event_id", "sm_occurrence_key", "sm_occurrence_start", "sm_status"):
        assert by_key[key]["indexed"] is True, key
    assert by_key["sm_nonce"]["system"] == "internal"
    assert all(by_key[k]["system"] == "readonly" for k in SYSTEM if k != "sm_nonce")
    assert by_key["sm_event_title"]["constraints"] == {"max_length": 300}
    assert body["display_field"] == "sm_name"
    assert body["public_submissions"]["pending_hold_hours"] == 24
    assert body["public_submissions"]["double_opt_in"] is True


@pytest.mark.parametrize("hours", [0, 169, -1])
async def test_hold_hours_out_of_range(site, hours):
    resp = await registration_type(site, pending_hold_hours=hours)
    assert resp.status_code == 422


@pytest.mark.parametrize("hours", [1, 168])
async def test_hold_hours_at_the_limits(site, hours):
    resp = await registration_type(site, pending_hold_hours=hours)
    assert (
        resp.status_code == 201 and resp.json()["public_submissions"]["pending_hold_hours"] == hours
    )


async def test_hold_hours_belong_to_registration(site):
    resp = await create(site, "contact", config={"kind": "form", "pending_hold_hours": 5})
    assert resp.status_code == 422


async def test_single_opt_in_needs_consent(site):
    bad = await registration_type(site, double_opt_in=False)
    assert bad.status_code == 422 and "double opt-in" in bad.text
    good = await registration_type(
        site, double_opt_in=False, consent={"required": True, "text": {"en": "I agree"}}
    )
    assert good.status_code == 201


async def test_the_kind_is_set_once(site):
    await registration_type(site)
    for kind in ("form", "subscription"):
        resp = await update(site, TYPE, public_submissions={**reg_config(), "kind": kind})
        assert resp.status_code == 409, kind
    other = await create(site, "contact")
    resp = await update(site, "contact", public_submissions={**reg_config()})
    assert other.status_code == 201 and resp.status_code == 409


async def test_visitors_cannot_fill_system_fields_through_public_fields(site):
    resp = await registration_type(site, public_fields=["diet", "sm_event_id"])
    assert resp.status_code == 422


async def test_the_generic_form_route_never_serves_it(site):
    await registration_type(site)
    resp = await site.get(f"{SUBMISSIONS}/{TYPE}")
    assert resp.status_code == 404
    missing = await site.get(f"{SUBMISSIONS}/nope")
    assert resp.json() == missing.json() and resp.headers["cache-control"] == "no-store"


async def test_listing_shows_the_kind_to_admins_only(site):
    await registration_type(site)
    got = await site.get(f"/api/records/types/{TYPE}", headers=roles(ADMIN))
    assert got.json()["public_submissions"]["kind"] == "registration"
    assert reg_fields()
