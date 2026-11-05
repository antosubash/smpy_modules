from pathlib import Path

import pytest
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.richtext import DROP_CONTENT, clean, to_email_html, to_text
from sm_newsletter.core.errors import InvalidBody

FIXTURES = Path(__file__).parent / "fixtures"
GDOCS = (FIXTURES / "gdocs_paste.html").read_text()


def test_drops_script_and_contents():
    assert clean("<p>a<script>alert(1)</script>b</p>") == "<p>ab</p>"


@pytest.mark.parametrize("tag", sorted(DROP_CONTENT))
def test_drop_tags_lose_contents(tag):
    assert clean(f"<p>a</p><{tag}>secret <p>x</p></{tag}><p>b</p>") == "<p>a</p><p>b</p>"


def test_nested_drop_tag_and_unclosed():
    assert clean("<p>a</p><svg><svg>x</svg>y</svg>z") == "<p>a</p>z"
    assert clean("<p>a</p><script>never closed") == "<p>a</p>"


def test_strips_event_handlers():
    assert clean("<p onclick=x>hi</p>") == "<p>hi</p>"
    assert clean('<strong style="x" onmouseover="y">hi</strong>') == "<strong>hi</strong>"


def test_javascript_href_dropped_keeps_text():
    assert clean('<a href="javascript:alert(1)">click</a>') == "click"


@pytest.mark.parametrize(
    "href",
    [
        "&#106;avascript:alert(1)",
        "java\tscript:alert(1)",
        "java&#9;script:alert(1)",
        "  javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "\x01javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/x",
        "",
    ],
)
def test_dangerous_hrefs_dropped(href):
    out = clean(f'<a href="{href}">click</a>')
    assert out == "click"


def test_entity_encoded_quotes_in_href_cannot_break_out():
    out = clean('<a href="https://x.example/&quot;onmouseover=&quot;alert(1)">t</a>')
    assert out.count('"') == 2  # only the attribute's own quotes
    assert "&quot;onmouseover=&quot;" in out
    assert clean(out) == out
    out = clean("<a href='https://x.example/&#39;onclick=&#39;x'>t</a>")
    assert "'" not in out and clean(out) == out


def test_href_whitespace_inside_scheme_is_normalised_not_trusted():
    assert clean('<a href="ht\ntps://x.example/a">t</a>') == '<a href="https://x.example/a">t</a>'
    assert clean('<a href=" https://x.example/a ">t</a>') == '<a href="https://x.example/a">t</a>'


def test_allowed_links_kept():
    for href in (
        "https://x.example/a?b=1&c=2",
        "mailto:a@b.example",
        "/p/x",
        "{{unsubscribe_url}}",
    ):
        out = clean(f'<a href="{href}" target=_blank onclick=x>t</a>')
        assert out.startswith("<a href=") and out.endswith(">t</a>")
        assert "target" not in out and "onclick" not in out
    assert clean('<a href="https://x.example/?a=1&amp;b=2">t</a>') == (
        '<a href="https://x.example/?a=1&amp;b=2">t</a>'
    )
    assert clean('<a href="{{unsubscribe_url}}">u</a>') == '<a href="{{unsubscribe_url}}">u</a>'


def test_merge_field_in_href_other_than_unsubscribe_dropped():
    assert clean('<a href="https://x.example/{{first_name}}">t</a>') == "t"


def test_duplicate_href_first_wins():
    out = clean('<a href="https://a.example/" href="javascript:alert(1)">t</a>')
    assert out == '<a href="https://a.example/">t</a>'
    assert clean('<a href="javascript:alert(1)" href="https://a.example/">t</a>') == "t"


def test_anchor_without_href_does_not_close_outer():
    out = clean('<a href="https://a.example/">x<a>y</a>z</a>w')
    assert out == '<a href="https://a.example/">xyz</a>w'


def test_nested_anchor_unwrapped():
    out = clean('<a href="https://a.example/">x<a href="https://b.example/">y</a>z</a>')
    assert out == '<a href="https://a.example/">xyz</a>'


def test_b_i_mapped():
    assert clean("<b>x</b><i>y</i>") == "<strong>x</strong><em>y</em>"


def test_unknown_tag_unwrapped():
    assert clean('<span style="color:red">hi</span>') == "hi"
    assert clean("<h1>Title</h1><div>d</div><code>c</code>") == "Titledc"


def test_entities_escaped():
    assert clean("<p>&lt;script&gt;</p>") == "<p>&lt;script&gt;</p>"
    assert clean("<p>a & b</p>") == "<p>a &amp; b</p>"
    assert clean("<p>&lt;img src=x onerror=y&gt;</p>") == "<p>&lt;img src=x onerror=y&gt;</p>"


def test_unclosed_tags_closed():
    assert clean("<p><strong>a<em>b") == "<p><strong>a<em>b</em></strong></p>"


def test_stray_end_tags_ignored():
    assert clean("a</p></strong>b") == "ab"


def test_malformed_nesting():
    assert clean("<p><b>x</p>y</b>") == "<p><strong>x</strong></p>y"
    assert clean("<p>a<p>b") == "<p>a<p>b</p></p>"
    assert clean("<b><i>x</b></i>") == "<strong><em>x</em></strong>"


def test_script_inside_allowed_tags():
    assert clean("<p>a<script>x</script></p><ul><li><script>y</script>z</li></ul>") == (
        "<p>a</p><ul><li>z</li></ul>"
    )
    assert clean('<a href="https://a.example/"><script>x</script>t</a>') == (
        '<a href="https://a.example/">t</a>'
    )


def test_style_and_svg_dropped():
    assert clean("<p>a</p><style>p{color:red}</style><svg onload=x><circle/></svg>") == "<p>a</p>"
    assert clean("<p>a<svg><script>x</script></svg>b</p>") == "<p>ab</p>"


def test_comments_and_declarations_dropped():
    assert clean("<p>a<!-- <script>x</script> -->b</p>") == "<p>ab</p>"
    assert clean("<!--[if gte mso 9]><xml>x</xml><![endif]--><p>a</p>") == "<p>a</p>"
    assert clean("<!DOCTYPE html><?php x ?><![CDATA[y]]><p>a</p>") == "<p>a</p>"


def test_truncated_markup_is_text_not_a_tag():
    out = clean("<p>a</p><scr")
    assert "<scr" not in out
    assert clean(out) == out


def test_depth_cap():
    n = 25
    out = clean("<blockquote>" * n + "x" + "</blockquote>" * n)
    assert out.count("<blockquote>") == 20
    assert out.count("</blockquote>") == 20
    assert "x" in out
    assert clean(out) == out


def test_br_is_void():
    assert clean("a<br>b<br/>c</br>d") == "a<br>b<br>cd"


FIXTURE_CASES = [
    GDOCS,
    '<p onclick=x>a<script>x</script><a href="javascript:x">b</a><b>c<i>d</p>',
    "<p>&#123;&#123;first_name|Hi&#125;&#125; &amp; &lt;b&gt;</p>",
    "<blockquote>" * 30 + "x",
    "plain & text <scr",
]


@pytest.mark.parametrize("raw", FIXTURE_CASES)
def test_idempotent(raw):
    once = clean(raw)
    assert clean(once) == once


def test_google_docs_paste():
    assert clean(GDOCS) == (
        "<p>Hello there"
        '<a href="https://www.google.com/url?q=https://example.com/a&amp;sa=D">our site</a></p>'
        "<ul><li><p>One</p></li><li><p>Two</p></li></ul><br><br>\n"
    )


def test_merge_tag_in_text_survives():
    assert clean("<p>{{first_name|Hi}} there</p>") == "<p>{{first_name|Hi}} there</p>"
    assert clean("<p>{{unsubscribe_url}}</p>") == "<p>{{unsubscribe_url}}</p>"


def test_to_email_html_styles_every_tag():
    out = to_email_html(
        '<p>a<br><strong>b</strong><a href="https://x.example/?a=1&amp;b=2">c</a></p>'
        "<ul><li>d</li></ul><ol><li>e</li></ol><blockquote><em>f</em><u>g</u><s>h</s></blockquote>",
        accent="#aa0000",
    )
    assert out.count("style=") == 11
    assert "<br>" in out
    assert 'href="https://x.example/?a=1&amp;b=2" style="color:#aa0000;' in out
    assert out.startswith('<p style="')


def test_to_email_html_rejects_non_colour_accent():
    with pytest.raises(ValueError):
        to_email_html("<p>x</p>", accent='red;" onload="x')


def test_to_text_lists_and_links():
    cleaned = (
        "<p>Hi <strong>you</strong><br>second line</p><ul><li>One</li><li>Two</li></ul>"
        '<ol><li>A</li><li>B</li></ol><p><a href="https://x.example/a">our site</a> and '
        '<a href="https://y.example/">https://y.example/</a></p><blockquote>quote</blockquote>'
    )
    assert to_text(cleaned) == (
        "Hi you\nsecond line\n\n- One\n- Two\n\n1. A\n2. B\n\n"
        "our site (https://x.example/a) and https://y.example/\n\nquote"
    )


def test_to_text_decodes_entities_and_collapses_space():
    assert to_text("<p>a &amp;   b &lt;c&gt;</p>") == "a & b <c>"


def test_blocks_rich_text_stores_cleaned():
    body = [
        {
            "type": "RichText",
            "props": {"id": "a", "html": "<p onclick=x><b>hi</b><script>x</script></p>"},
        }
    ]
    assert parse_body(body)[0].props.html == "<p><strong>hi</strong></p>"


def test_blocks_rich_text_checks_merge_on_cleaned_output():
    for raw in (
        "<p>&#123;&#123;last_name&#125;&#125;</p>",
        "<p>{{last_<b>name}}</p>",
        "<p>{{nope}}</p>",
    ):
        with pytest.raises(InvalidBody):
            parse_body([{"type": "RichText", "props": {"id": "a", "html": raw}}])
    ok = parse_body(
        [
            {
                "type": "RichText",
                "props": {"id": "a", "html": "<p>&#123;&#123;first_name|Hi&#125;&#125;</p>"},
            }
        ]
    )
    assert ok[0].props.html == "<p>{{first_name|Hi}}</p>"
