import logging

import pytest
from sm_newsletter.content.render import render
from sm_newsletter.tracking.rewrite import PIXEL_TAG, Tracking, fill, prepare

from tests.content.test_render import CARD, body, ctx, inp

BASE = "https://pub.example.org"
A = "https://a.example.org/x"
B = "https://b.example.org/y"


def _html(*hrefs: str, tail: str = "") -> str:
    links = "".join(f'<p><a href="{h}">l</a></p>' for h in hrefs)
    return f"<html><body>{links}{tail}</body></html>"


def test_prepare_rewrites_http_links_in_order():
    out = prepare(_html(A, B, A), own_base=BASE)
    assert out.links == (A, B)
    assert out.html.count('href="{{link:1}}"') == 2
    assert out.html.count('href="{{link:2}}"') == 1


@pytest.mark.parametrize(
    "href",
    [
        "{{unsubscribe_url}}",
        "mailto:x@example.org",
        "https://pub.example.org/newsletter/brand/logo",
        "javascript:x",
    ],
)
def test_prepare_skips_untrackable(href):
    out = prepare(_html(href), own_base=BASE)
    assert f'href="{href}"' in out.html and out.links == ()


def test_prepare_ignores_img_src():
    out = prepare('<body><img src="https://e.org/a.png"></body>', own_base=BASE)
    assert 'src="https://e.org/a.png"' in out.html and out.links == ()


def test_prepare_unescapes_href():
    out = prepare(_html("https://e.org/?a=1&amp;b=2#f"), own_base=BASE)
    assert out.links == ("https://e.org/?a=1&b=2#f",)


def test_prepare_caps_distinct_links(caplog):
    urls = [f"https://e.org/{i}" for i in range(101)]
    with caplog.at_level(logging.WARNING):
        out = prepare(_html(*urls), own_base=BASE)
    assert len(out.links) == 100
    assert f'href="{urls[100]}"' in out.html
    assert len(caplog.records) == 1


def test_prepare_leaves_overlong_url():
    url = "https://e.org/" + "a" * (2049 - 14)
    assert len(url) == 2049
    out = prepare(_html(url), own_base=BASE)
    assert out.links == () and url in out.html


def test_prepare_inserts_one_pixel_before_body_end():
    out = prepare(_html(A), own_base=BASE).html
    assert out.count(PIXEL_TAG) == 1
    assert out.endswith(f"{PIXEL_TAG}</body></html>")
    assert prepare("<p>x</p>", own_base=BASE).html == f"<p>x</p>{PIXEL_TAG}"


@pytest.mark.parametrize("bad", ["{{link:1}}", PIXEL_TAG])
def test_prepare_refuses_existing_placeholders(bad):
    with pytest.raises(ValueError):
        prepare(f"<body>{bad}</body>", own_base=BASE)


def test_card_links_share_a_position():
    out = render(inp(body(("ArticleCard", {**CARD, "url": "https://news.example.org/a"}))), ctx())
    prepared = prepare(out.html, own_base="https://example.org")
    assert prepared.links == ("https://news.example.org/a",)


def _fill(html, *, tracking, links=None):
    return fill(
        html,
        open_token="OT",
        click_token="CT",
        public_base=BASE + "/",
        links=links or {},
        tracking=tracking,
    )


def test_fill_clicks_on():
    prepared = prepare(_html(A, B), own_base=BASE)
    out = _fill(prepared.html, tracking=Tracking(opens=False, clicks=True))
    assert f'href="{BASE}/newsletter/c/CT/1"' in out
    assert f'href="{BASE}/newsletter/c/CT/2"' in out
    assert "{{" not in out


def test_fill_clicks_off_restores_original():
    prepared = prepare(_html("https://e.org/?a=1&amp;b=2"), own_base=BASE)
    links = dict(enumerate(prepared.links, 1))
    out = _fill(prepared.html, tracking=Tracking(opens=False, clicks=False), links=links)
    assert 'href="https://e.org/?a=1&amp;b=2"' in out


def test_fill_opens_on_off():
    html = prepare(_html(A), own_base=BASE).html
    on = _fill(html, tracking=Tracking(opens=True, clicks=False), links={1: A})
    assert f'src="{BASE}/newsletter/o/OT.gif"' in on and 'width="1"' in on
    off = _fill(html, tracking=Tracking(opens=False, clicks=False), links={1: A})
    assert "<img" not in off and PIXEL_TAG not in off


def test_fill_unknown_position_clicks_off_raises():
    html = prepare(_html(A), own_base=BASE).html
    with pytest.raises(ValueError):
        _fill(html, tracking=Tracking(opens=False, clicks=False), links={})


def test_fill_leaves_merge_tags():
    html = prepare(_html(A, tail="Hi {{first_name|x}} {{unsubscribe_url}}"), own_base=BASE).html
    out = _fill(html, tracking=Tracking(opens=True, clicks=True))
    assert "{{first_name|x}}" in out and "{{unsubscribe_url}}" in out
