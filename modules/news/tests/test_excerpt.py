"""Excerpt extraction. Sync tests, so deliberately not under the asyncio mark."""

from __future__ import annotations

from news import search_service

BODY = {"content": [{"type": "Heading", "props": {"text": "mixed canopy cover rose 4%"}}]}


class TestExcerpt:
    def test_it_returns_the_text_around_the_match(self) -> None:
        found = search_service.excerpt(BODY, "canopy")

        assert "canopy" in found
        # Reads as prose, not as a fragment of a data structure.
        assert '"' not in found and "{" not in found

    def test_no_match_gives_nothing(self) -> None:
        assert search_service.excerpt(BODY, "kangaroo") == ""

    def test_empty_blocks_give_nothing(self) -> None:
        assert search_service.excerpt(None, "canopy") == ""
        assert search_service.excerpt({}, "canopy") == ""

