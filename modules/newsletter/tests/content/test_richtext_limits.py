import pytest
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.richtext import clean
from sm_newsletter.core.errors import InvalidBody


@pytest.mark.parametrize(
    "raw",
    [
        "<p><strong>{{first_name|</strong>}}</strong></p>",
        "<p><a href='https://a.example/'>{{first_name|</a>}}</a></p>",
        "<p>{{first_name|<b>x</b>}}</p>",
    ],
)
def test_merge_fallback_cannot_span_markup(raw):
    with pytest.raises(InvalidBody):
        parse_body([{"type": "RichText", "props": {"id": "a", "html": raw}}])


def test_escaped_text_fallback_is_plain_text_and_allowed():
    raw = "<p>{{first_name|a &lt;b&gt;}}</p>"
    got = parse_body([{"type": "RichText", "props": {"id": "a", "html": raw}}])
    assert got[0].props.html == raw


def test_merge_fallback_length_counts_unescaped():
    ok = "<p>{{first_name|" + "&amp;" * 100 + "}}</p>"
    assert parse_body([{"type": "RichText", "props": {"id": "a", "html": ok}}])
    with pytest.raises(InvalidBody):
        bad = "<p>{{first_name|" + "&amp;" * 101 + "}}</p>"
        parse_body([{"type": "RichText", "props": {"id": "a", "html": bad}}])


def test_control_characters_stripped_from_text():
    assert clean("<p>a\x00b\x07c\x1fd\x7fe\tf\ng</p>") == "<p>abcde\tf\ng</p>"


def test_pathological_nesting_is_fast():
    import time

    start = time.monotonic()
    body = [{"type": "RichText", "props": {"id": f"b{i}", "html": "<p>" * 6666}} for i in range(10)]
    parse_body(body)
    clean("<b>" * 3000 + "</i>" * 3000)
    assert time.monotonic() - start < 2
