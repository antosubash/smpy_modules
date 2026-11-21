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
EVENT_ID = "3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11"
EVENT = {
    "source_id": EVENT_ID,
    "title": "Open day",
    "excerpt": "Come by",
    "image_url": "/media/a.png",
    "url": "/events/open-day?date=2026-07-01",
    "ics_url": "/events/open-day.ics",
    "locale": "en",
    "starts_at": "2026-07-01T08:00:00Z",
    "ends_at": "2026-07-01T09:00:00Z",
    "all_day": False,
    "start_date": None,
    "end_date": None,
    "timezone": "Europe/Vienna",
    "attendance_mode": "hybrid",
    "place": "Hall 1, Main St 2",
    "cancelled": False,
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
    {"type": "EventCard", "props": {"id": "i", **EVENT}},
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


def _event_body(**changes):
    return [{"type": "EventCard", "props": {"id": "e", **EVENT, **changes}}]


def test_event_card_props_valid():
    assert dump_body(parse_body(_event_body())) == _event_body()
    all_day = _event_body(all_day=True, start_date="2026-03-29", end_date="2026-03-30")
    assert dump_body(parse_body(all_day)) == all_day


@pytest.mark.parametrize(
    "changes, path",
    [
        ({"source_id": "7"}, "body[0].props.source_id"),
        ({"source_id": 7}, "body[0].props.source_id"),
        ({"ends_at": "2026-07-01T08:00:00Z"}, "body[0].props"),
        ({"all_day": True}, "body[0].props"),
        ({"start_date": "2026-07-01", "end_date": "2026-07-02"}, "body[0].props"),
        ({"all_day": True, "start_date": "2026-07-02", "end_date": "2026-07-02"}, "body[0].props"),
        ({"timezone": "Mars/Base"}, "body[0].props.timezone"),
        ({"ics_url": "javascript:alert(1)"}, "body[0].props.ics_url"),
        ({"url": "https://evil.example/"}, "body[0].props.url"),
        ({"url": "mailto:a@evil.example"}, "body[0].props.url"),
        ({"url": "//evil.example/x"}, "body[0].props.url"),
        ({"url": "/a\\b"}, "body[0].props.url"),
        ({"url": "/a\r\nb"}, "body[0].props.url"),
        ({"url": ""}, "body[0].props.url"),
        ({"url": "{{unsubscribe_url}}"}, "body[0].props.url"),
        ({"ics_url": "https://evil.example/e.ics"}, "body[0].props.ics_url"),
        ({"image_url": "https://evil.example/x.png"}, "body[0].props.image_url"),
        ({"image_url": "//evil.example/x.png"}, "body[0].props.image_url"),
        ({"url": "{{unsubscribe_url}}x"}, "body[0].props.url"),
        ({"starts_at": "2026-07-01T08:00:00"}, "body[0].props.starts_at"),
        ({"attendance_mode": "teleport"}, "body[0].props.attendance_mode"),
        ({"onclick": "x"}, "body[0].props.onclick"),
    ],
)
def test_event_card_props_refused(changes, path):
    with pytest.raises(InvalidBody) as exc:
        parse_body(_event_body(**changes))
    assert exc.value.detail.startswith(path)
    assert "javascript" not in exc.value.detail and "Mars" not in exc.value.detail
