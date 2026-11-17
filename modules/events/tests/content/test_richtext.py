"""The description sanitiser: an allow-list re-serialiser, hostile input included."""

from __future__ import annotations

import random

import pytest
from sm_events.content.richtext import ALLOWED_TAGS, clean
from sm_events.core import constants
from sm_events.core.errors import DescriptionTooLong


@pytest.mark.parametrize("tag", sorted(ALLOWED_TAGS - {"br", "a"}))
def test_allowed_kept(tag):
    assert clean(f"<{tag}>x</{tag}>") == f"<{tag}>x</{tag}>"


def test_br_and_link_kept():
    assert clean("a<br>b") == "a<br>b"
    assert (
        clean('<a href="https://a/b?c=1&amp;d=2">x</a>')
        == '<a href="https://a/b?c=1&amp;d=2">x</a>'
    )


def test_attributes_dropped():
    assert clean('<p style="color:red" onclick="x()" class="c" id="i">t</p>') == "<p>t</p>"
    assert clean('<a href="https://a" onclick="x()" target="_blank" rel="x">t</a>') == (
        '<a href="https://a">t</a>'
    )


def test_img_and_events_gone():
    assert clean("<img src=x onerror=alert(1)>") == ""
    assert clean("<body onload=alert(1)>t</body>") == "t"


@pytest.mark.parametrize("tag", ["script", "style", "svg", "iframe", "math", "template"])
def test_script_style_svg_contents_dropped(tag):
    assert clean(f"a<{tag}>alert(1)<b>x</b></{tag}>b") == "ab"


def test_nested_dropped_content():
    # script is raw text up to the first </script>, in browsers too: "y" is plain,
    # escaped text and the stray closer is ignored.
    assert clean("<script><script>x</script>y</script>z") == "yz"
    assert clean("<svg><svg><script>x</script></svg>y</svg>z") == "z"


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " jav&#x09;ascript:alert(1)",
        "java\nscript:alert(1)",
        "jav&#x0A;ascript:alert(1)",
        "&#106;avascript:alert(1)",
        "&#x6A;&#x61;vascript:alert(1)",
        "java&colon;script:1",
        "\x01javascript:alert(1)",
        "\u200bjavascript:alert(1)",
        "java\u200bscript:alert(1)",
        "javascript\u2028:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "ftp://a/b",
        "//evil.example/x",
        "/x",
        "x",
        "https:///x",
        "http://",
        "mailto:",
        "https://a b",
        "",
    ],
)
def test_href_refused_is_unwrapped(href):
    out = clean(f'<a href="{href}">label</a>')
    assert out == "label"
    assert "href" not in out and "script" not in out.lower().replace("label", "")


@pytest.mark.parametrize("href", ["https://a", "http://a/b", "mailto:x@y", "HTTPS://A/B"])
def test_href_schemes_kept(href):
    assert clean(f'<a href="{href}">t</a>') == f'<a href="{href}">t</a>'


def test_href_quote_injection_is_escaped():
    assert clean("<a href='https://a/\" onmouseover=\"x()'>t</a>") == "t"  # a space refuses it
    out = clean("<a href='https://a/\"onmouseover=x'>t</a>")
    assert out == '<a href="https://a/&quot;onmouseover=x">t</a>'
    assert out.count('"') == 2  # only the attribute's own quotes


def test_duplicate_href_keeps_first():
    assert clean('<a href="https://a" href="javascript:x">t</a>') == '<a href="https://a">t</a>'


def test_nested_anchor_unwrapped():
    out = clean('<a href="https://a">one <a href="https://b">two</a> three</a>')
    assert out == '<a href="https://a">one two three</a>'


def test_text_is_escaped():
    assert clean("1 < 2 & 3 > 2") == "1 &lt; 2 &amp; 3 &gt; 2"
    assert clean("&lt;script&gt;alert(1)&lt;/script&gt;") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_control_characters_stripped_from_text():
    assert clean("a\x00b\x07c\x1fd") == "abcd"


def test_unclosed_and_misnested():
    assert clean("<p><em>x") == "<p><em>x</em></p>"
    assert clean("<p><em>x</p>y</em>") == "<p><em>x</em></p>y"
    assert clean("</p></em>text") == "text"


def test_depth_cap():
    out = clean("<em>" * 25 + "x" + "</em>" * 25)
    assert out.count("<em>") == 20 and out.count("</em>") == 20
    assert out == clean(out)


def test_b_i_renamed():
    assert clean("<b>x</b><i>y</i>") == "<strong>x</strong><em>y</em>"


def test_bounds():
    with pytest.raises(DescriptionTooLong) as raised:
        clean("x" * (constants.DESCRIPTION_RAW_MAX + 1))
    assert raised.value.code == constants.DESCRIPTION_TOO_LONG_CODE
    assert clean("x" * constants.DESCRIPTION_MAX) == "x" * constants.DESCRIPTION_MAX
    with pytest.raises(DescriptionTooLong):
        clean("x" * (constants.DESCRIPTION_MAX + 1))


def test_cleaned_output_bound():
    # 40,000 "&" is 40,000 characters in, 200,000 out once escaped.
    with pytest.raises(DescriptionTooLong):
        clean("&" * 40_000)


_PIECES = [
    "<p>",
    "</p>",
    "<em>",
    "</em>",
    "<b>",
    "</b>",
    '<a href="https://a">',
    "<a href='javascript:x'>",
    "</a>",
    "<br>",
    "<br/>",
    "<ul>",
    "<li>",
    "</ul>",
    "<script>",
    "</script>",
    "<svg>",
    "</svg>",
    "&amp;",
    "&lt;",
    "&#x3c;",
    "<",
    ">",
    "&",
    "text",
    " ",
    "\n",
    "\x00",
    "<h2>",
    "</h2>",
    "<img src=x>",
    "<!--",
    "-->",
    "<![CDATA[",
    "]]>",
    '<a href="mailto:a@b">',
    '"',
    "'",
]


def test_idempotent():
    rng = random.Random(0)
    for _ in range(200):
        raw = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 40)))
        once = clean(raw)
        assert clean(once) == once, raw


def test_output_never_carries_executable_markup():
    rng = random.Random(1)
    for _ in range(200):
        raw = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 40)))
        out = clean(raw).lower()
        for needle in ("<script", "<svg", "<img", "javascript:", " on"):
            assert needle not in out, (raw, out)
