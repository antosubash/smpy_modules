"""The one rule for "an image the site may show": a path on the site, or the site's own origin."""

from __future__ import annotations

import pytest
from sm_events.core.web_urls import is_site_image

ORIGIN = "https://example.org"


@pytest.mark.parametrize(
    "value",
    ["/media/a.png", "/static/x/y.jpg?v=2", "/a", f"{ORIGIN}/media/a.png", f"{ORIGIN}:443/x.png"],
)
def test_the_sites_own_images(value):
    assert is_site_image(value, ORIGIN) is True


@pytest.mark.parametrize(
    "value",
    [
        "https://cdn.example.net/a.png",
        "//cdn.example.net/a.png",
        "http://example.org/a.png",  # another scheme is another origin
        "https://example.org.evil.example/a.png",
        "https://user:pw@example.org/a.png",
        "https://example.org@evil.example/a.png",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "/a\\b",
        "/a b",
        "/a\r\nb",
        "relative.png",
        "",
    ],
)
def test_everything_else_is_refused(value):
    assert is_site_image(value, ORIGIN) is False


def test_without_an_origin_only_a_path_counts():
    assert is_site_image("/media/a.png") is True
    assert is_site_image(f"{ORIGIN}/media/a.png") is False
