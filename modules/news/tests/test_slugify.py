"""Slug derivation. Sync tests, so deliberately not under the asyncio mark."""

from __future__ import annotations

from news.slugify import slugify, unique_slug


class TestSlugify:
    def test_folds_accents_rather_than_dropping_them(self) -> None:
        # Dropping would collapse "Étude" and "tude" onto the same slug.
        assert slugify("Étude de terrain") == "etude-de-terrain"

    def test_falls_back_when_nothing_survives(self) -> None:
        assert slugify("…", fallback="category") == "category"

    def test_never_ends_in_a_separator_after_truncation(self) -> None:
        assert not slugify("a" * 9 + " " + "b" * 40, max_length=10).endswith("-")

    def test_unique_slug_suffixes_within_the_length_limit(self) -> None:
        taken = {"field-note"}
        out = unique_slug("field note", taken, max_length=10)
        assert out not in taken
        assert len(out) <= 10

