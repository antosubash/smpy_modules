"""The description as a render-safe node tree."""

from __future__ import annotations

import json

import pytest
from sm_events.content.richtext import ALLOWED_TAGS
from sm_events.content.richtext_tree import to_tree


def test_simple():
    assert to_tree("<p>a <strong>b</strong></p>") == [
        {"t": "p", "c": ["a ", {"t": "strong", "c": ["b"]}]}
    ]


def test_link_href_kept_only_safe():
    ok = to_tree('<p><a href="https://example.org/x">site</a></p>')
    assert ok == [{"t": "p", "c": [{"t": "a", "href": "https://example.org/x", "c": ["site"]}]}]
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.example", "vbscript:x"):
        out = to_tree(f'<p><a href="{bad}">x</a></p>')
        assert out == [{"t": "p", "c": ["x"]}], bad


def test_entities_are_text():
    out = to_tree("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")
    assert out == [{"t": "p", "c": ["<script>alert(1)</script>"]}]


def test_void_br():
    assert to_tree("<p>a<br>b</p>") == [{"t": "p", "c": ["a", {"t": "br", "c": []}, "b"]}]


def test_script_and_handlers_never_survive():
    out = to_tree("<p onclick=x>Hi <script>bad()</script></p>")
    assert out == [{"t": "p", "c": ["Hi "]}]
    assert "bad" not in json.dumps(out)


def test_round_trip_every_allowed_tag():
    samples = {
        "p": "<p>x</p>",
        "br": "<p>a<br>b</p>",
        "strong": "<p><strong>x</strong></p>",
        "em": "<p><em>x</em></p>",
        "u": "<p><u>x</u></p>",
        "s": "<p><s>x</s></p>",
        "a": '<p><a href="https://e.org/">x</a></p>',
        "ul": "<ul><li>x</li></ul>",
        "ol": "<ol><li>x</li></ol>",
        "li": "<ul><li>x</li></ul>",
        "blockquote": "<blockquote><p>x</p></blockquote>",
        "h2": "<h2>x</h2>",
        "h3": "<h3>x</h3>",
    }
    assert set(samples) == set(ALLOWED_TAGS)

    def tags(nodes):
        for node in nodes:
            if isinstance(node, dict):
                yield node["t"]
                yield from tags(node["c"])

    for tag, html in samples.items():
        assert tag in set(tags(to_tree(html))), tag


def test_only_allowed_tags_in_the_output():
    nodes = to_tree("<div><span>a</span><p>b</p><table><tr><td>c</td></tr></table></div>")

    def walk(items):
        for node in items:
            if isinstance(node, dict):
                assert node["t"] in ALLOWED_TAGS
                walk(node["c"])

    walk(nodes)
    assert "a" in json.dumps(nodes) and "c" in json.dumps(nodes)


@pytest.mark.parametrize("html", ["", "<p></p>", "   "])
def test_empty(html):
    assert to_tree(html) == []


def test_json_serialisable():
    out = to_tree('<h2>T</h2><p>a <a href="mailto:x@y.org">m</a></p><ul><li>i</li></ul>')
    assert json.loads(json.dumps(out)) == out


def test_depth_is_bounded():
    deep = "<blockquote>" * 60 + "x" + "</blockquote>" * 60
    out = to_tree(deep)

    def depth(nodes):
        return 1 + max((depth(n["c"]) for n in nodes if isinstance(n, dict)), default=0)

    assert depth(out) <= 25
