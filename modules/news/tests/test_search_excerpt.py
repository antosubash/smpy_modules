"""The search excerpt is a sentence from the page, not a dump of its shape.

Stripping JSON punctuation left the *keys* behind, so a page whose match sat
near the start of the payload rendered as
``root : props : title : … width : full content : zones :`` on the search
screen. The keys are structure, never prose, so the excerpt reads values only.
"""

from __future__ import annotations

from news.search_service import excerpt

BLOCKS = {
    "root": {"props": {"title": "Canopy survey", "width": "full"}},
    "content": [
        {
            "type": "Text",
            "props": {
                "id": "t1",
                "text": "Plot 14 was resurveyed in March after the storm damage.",
            },
        }
    ],
    "zones": {},
}

# Every JSON key in the payload above. None may appear in an excerpt.
STRUCTURE_WORDS = ("root", "props", "width", "content", "zones", "type")


def test_the_excerpt_is_prose_from_the_page() -> None:
    found = excerpt(BLOCKS, "resurveyed")

    assert "Plot 14 was resurveyed in March" in found


def test_no_json_key_leaks_into_the_excerpt() -> None:
    """The actual reported symptom."""
    found = excerpt(BLOCKS, "Canopy").lower()

    for key in STRUCTURE_WORDS:
        assert key not in found, f"structure word {key!r} leaked into: {found!r}"


def test_a_match_only_in_the_title_still_reads_as_text() -> None:
    found = excerpt(BLOCKS, "Canopy")

    assert "Canopy survey" in found
    assert ":" not in found


def test_no_match_is_empty():
    assert excerpt(BLOCKS, "nothing-here") == ""


def test_empty_inputs_are_empty() -> None:
    assert excerpt(None, "x") == ""
    assert excerpt(BLOCKS, "   ") == ""


def test_deeply_nested_prose_is_still_found() -> None:
    """Blocks nest arbitrarily — a column inside a grid inside a section."""
    nested = {"content": [{"props": {"items": [{"body": "Deep sentence here."}]}}]}

    assert "Deep sentence here." in excerpt(nested, "Deep sentence")
