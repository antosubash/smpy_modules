"""A malformed or external-item-shaped event id or occurrence key is answered like an unknown
event, never a server error: the panel API, the submit route and a forged token."""

from __future__ import annotations

import uuid

import pytest

from tests.support.registration_http import ADDRESS, TYPE, load_registration
from tests.support.submissions_http import JSON, SUBMISSIONS

pytestmark = pytest.mark.usefixtures("reg_site")
SUBSCRIPTION = str(uuid.uuid4())  # what an external subscription's id looks like
BAD_KEYS = [
    "",
    "x",
    "subscriptions:42",  # an external item's key
    "42",
    f"{SUBSCRIPTION}",
    f"{SUBSCRIPTION}:20990701T080000Z",
    "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42:notatimestamp",
    "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42:20990701T080000Z:extra",
    "a" * 5000,
    "\x00",
    "é" * 40,
    "../../etc/passwd",
]


async def _unknown(site):
    return await site.get(f"{SUBMISSIONS}/nope/registration", params={"event": "x"})


@pytest.mark.parametrize("key", BAD_KEYS)
async def test_the_panel_api_answers_a_bad_key_like_an_unknown_event(reg_site, key):
    unknown = await _unknown(reg_site)
    for event_id in (reg_site.event["event_id"], SUBSCRIPTION, key):
        got = await load_registration(reg_site, {"event_id": event_id, "key": key})
        if len(key) > 200:  # the query's own length bound answers first: a validation error
            assert got.status_code == 422, (event_id, got.text[:200])
            continue
        assert got.status_code == 404 == unknown.status_code, (event_id, key, got.text[:200])
        assert got.text == unknown.text


@pytest.mark.parametrize("token", ["", "x", "a.b.c.d.e.f", "." * 6, "é" * 50, "a" * 5000])
async def test_submit_answers_a_forged_token_without_a_server_error(reg_site, token):
    body = {"data": {"sm_email": ADDRESS, "sm_name": "Ada"}, "token": token}
    got = await reg_site.post(f"{SUBMISSIONS}/{TYPE}/submit", json=body, headers=JSON)
    assert got.status_code < 500, got.text[:200]


async def test_the_my_registrations_route_has_no_key_to_get_wrong(reg_site):
    got = await reg_site.get("/api/records/registrations/mine?occurrence=%00&event=zz")
    assert got.status_code < 500, got.text[:200]
