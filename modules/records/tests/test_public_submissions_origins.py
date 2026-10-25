"""Website submissions (#101): origins compared as parsed tuples, and a stored
config that names a unique public field kept away from visitors."""

from __future__ import annotations

import pytest
from sm_records.public_submissions.abuse import origin_of

from tests.app_harness import field, seed_type
from tests.public_submissions_support import contact_fields, form_config
from tests.submissions_http import SUBMISSIONS, configure, contact_type, host_parts, load, send


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("https://[2001:db8::1]:8443", "https://[2001:db8::1:8443]", False),
        ("https://[2001:DB8::1]:8443", "https://[2001:db8::1]:8443/x", True),
        ("https://[2001:db8::1]", "https://[2001:db8::1]:443", True),
        ("https://Example.org:443/site", "https://example.org", True),
        ("https://example.org.", "https://example.org", True),
        ("http://example.org", "https://example.org", False),
        ("https://example.org:8443", "https://example.org", False),
    ],
)
def test_origins_compare_as_parsed_tuples(a, b, same):
    assert (origin_of(a) == origin_of(b)) is same


@pytest.mark.parametrize("bad", ["null", "file:///x", "https://", "not a url", "https://[::1"])
def test_what_is_not_an_origin(bad):
    assert origin_of(bad) is None


async def test_an_ipv6_origin_must_match_its_port(site):
    configure(site, public_submissions_allowed_origins=("https://[2001:db8::1]:8443",))
    await contact_type(site)
    ok = await send(site, headers={"Origin": "https://[2001:db8::1]:8443"})
    assert ok.status_code == 202, ok.text
    lookalike = await send(site, headers={"Origin": "https://[2001:db8::1:8443]"})
    assert lookalike.json()["code"] == "bad_origin"


async def test_a_null_origin_is_refused_even_with_a_referer(site):
    host_parts(site.app)
    await contact_type(site)
    resp = await send(site, headers={"Origin": "null", "Referer": "http://test/p/contact"})
    assert (resp.status_code, resp.json()["code"]) == (403, "bad_origin")


async def test_a_stored_unique_public_field_never_reaches_a_visitor(site):
    """A config stored before the save-time rule (unique fields cannot be
    public) existed: the form leaves the field out and a submission naming it
    is refused like any non-public field, so no 409 tells anyone what is stored."""
    fields = [*contact_fields(), field("ref", unique=True, indexed=True)]
    config = form_config(enabled=True, public_fields=["name", "email", "message", "ref"])
    await seed_type(
        site.db_state,
        "legacy",
        fields,
        public_submissions={
            **config,
            "consent": {"required": False, "text": {}},
            "notify_to": [],
            "double_opt_in": True,
            "retention_days": 365,
            "pending_purge_days": 30,
        },
    )
    definition = await load(site, "legacy")
    assert [f["key"] for f in definition["fields"]] == ["name", "email", "message"]
    data = {"name": "A", "email": "a@b.org", "message": "m", "ref": "R-1"}
    resp = await send(site, "legacy", data=data, token=definition["token"])
    assert (resp.status_code, resp.json()["code"]) == (422, "unknown_field")
    assert (await site.get(f"{SUBMISSIONS}/legacy")).status_code == 200
