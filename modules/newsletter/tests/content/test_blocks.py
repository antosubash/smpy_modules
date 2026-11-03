import copy

import pytest
from sm_newsletter.content.blocks import BLOCK_TYPES, dump_body, parse_body
from sm_newsletter.content.urls import UNSUBSCRIBE_TAG
from sm_newsletter.core.errors import InvalidBody

CARD = {
    "source_id": 4,
    "title": "T",
    "excerpt": "E",
    "image_url": "/i.png",
    "url": "/de/p/x",
    "locale": "de",
    "snapshot_at": "2026-11-03T10:00:00Z",
}
BODY = [
    {
        "type": "Heading",
        "props": {"id": "a", "text": "Hi {{first_name|Friend}}", "level": "1", "align": "center"},
    },
    {"type": "RichText", "props": {"id": "b", "html": "<p>Hello</p>"}},
    {
        "type": "Image",
        "props": {"id": "c", "src": "https://x/i.png", "alt": "", "href": None, "width": 600},
    },
    {
        "type": "Button",
        "props": {"id": "d", "label": "Go", "href": UNSUBSCRIBE_TAG, "align": "center"},
    },
    {"type": "Divider", "props": {"id": "e"}},
    {"type": "Spacer", "props": {"id": "f", "size": "md"}},
    {"type": "ArticleCard", "props": {"id": "g", **CARD}},
    {"type": "PageCard", "props": {"id": "h", **CARD}},
]


def test_round_trip():
    assert {b["type"] for b in BODY} == set(BLOCK_TYPES)
    assert dump_body(parse_body(copy.deepcopy(BODY))) == BODY


def test_unknown_type_422():
    with pytest.raises(InvalidBody) as exc:
        parse_body([{"type": "Video", "props": {"id": "a"}}])
    assert exc.value.status == 422 and exc.value.code == "invalid_body"
    assert exc.value.detail.startswith("body[0]")


def test_extra_prop_422():
    body = copy.deepcopy(BODY)
    body[3]["props"]["onclick"] = "x"
    with pytest.raises(InvalidBody) as exc:
        parse_body(body)
    assert exc.value.detail.startswith("body[3].props.onclick")


def test_bad_href_names_path():
    body = copy.deepcopy(BODY)
    body[3]["props"]["href"] = "javascript:alert(1)"
    with pytest.raises(InvalidBody) as exc:
        parse_body(body)
    assert exc.value.detail.startswith("body[3].props.href")
    assert "javascript" not in exc.value.detail


def test_duplicate_ids_422():
    body = copy.deepcopy(BODY)
    body[1]["props"]["id"] = "a"
    with pytest.raises(InvalidBody):
        parse_body(body)


def test_201_blocks_422():
    with pytest.raises(InvalidBody):
        parse_body([{"type": "Divider", "props": {"id": f"d{i}"}} for i in range(201)])
    assert (
        len(parse_body([{"type": "Divider", "props": {"id": f"d{i}"}} for i in range(200)])) == 200
    )


def test_not_a_list_and_naive_datetime():
    with pytest.raises(InvalidBody):
        parse_body({"type": "Divider"})
    body = copy.deepcopy(BODY)
    body[6]["props"]["snapshot_at"] = "2026-11-03T10:00:00"
    with pytest.raises(InvalidBody):
        parse_body(body)


def test_merge_rules_applied():
    with pytest.raises(InvalidBody):
        parse_body([{"type": "Heading", "props": {"id": "a", "text": "{{last_name}}"}}])
    with pytest.raises(InvalidBody):
        parse_body([{"type": "RichText", "props": {"id": "a", "html": "<p>{{nope}}</p>"}}])


def test_error_never_echoes_input():
    for text in ("<script>" * 625, "<script>\n"):
        with pytest.raises(InvalidBody) as exc:
            parse_body([{"type": "Heading", "props": {"id": "a", "text": text}}])
        assert "script" not in exc.value.detail
    with pytest.raises(InvalidBody) as exc:
        parse_body([{"type": "Heading", "props": {"id": "a", "text": "x", "<script>": 1}}])
    assert "script" not in exc.value.detail
