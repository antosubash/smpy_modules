"""A URL the module stores or shows never carries credentials, however it got in."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_events.feeds.importing.text import description_html, http_url, venue
from sm_events.web.schemas.events_in import EventPatch

CREDENTIALS = [
    "https://user:pw@evil.example/x",
    "https://user@evil.example/x",
    "http://:pw@evil.example/",
    "https://evil.example@good.example/",
]


@pytest.mark.parametrize("url", CREDENTIALS)
def test_the_editor_refuses_a_url_with_userinfo(url):
    for field in ("online_url", "image", "registration_url"):
        with pytest.raises(ValidationError):
            EventPatch(expected_revision=1, **{field: url})


@pytest.mark.parametrize("url", CREDENTIALS)
def test_the_importer_stores_none(url):
    assert http_url(url) is None
    assert "href" not in description_html("see", url)[0]


def test_ordinary_urls_still_pass_both_ways():
    ok = "https://example.org/path?a=b#frag"
    assert EventPatch(expected_revision=1, online_url=ok).online_url == ok
    assert http_url(ok) == ok
    assert http_url("http://example.org:8080/x") == "http://example.org:8080/x"


def test_credentials_in_a_place_name_are_scrubbed():
    assert "pw" not in (venue("Meet at https://user:pw@evil.example/room") or "")
    assert venue("Meet at https://example.org/room") == "Meet at https://example.org/room"
    assert "pw" not in description_html("Join https://user:pw@evil.example/x now", None)[0]
