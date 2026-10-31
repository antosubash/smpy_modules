"""Slug derivation. Sync tests, so deliberately not under the asyncio mark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from news.constants import MAX_SLUG_ATTEMPTS, MAX_SLUG_LEN
from news.slugify import slugify, suffixed, unique_slug

#: The one slug rule, shared with the two TypeScript implementations that
#: preview it — news' new-article dialog and pagebuilder's page editor. Read
#: from a file rather than restated in each, because a restated copy drifts
#: silently: pagebuilder's used to turn every letter NFKD leaves whole into a
#: separator while this module dropped it, so one headline produced two
#: different URLs depending on which admin screen it was typed into.
_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "tests/fixtures/slug_cases.json").read_text(
        encoding="utf-8"
    )
)


class TestSharedRule:
    """This module is the source of truth: it is the one with a database."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(c["input"], c["expected"]) for c in _FIXTURE["cases"]],
        ids=[c["input"] or "<empty>" for c in _FIXTURE["cases"]],
    )
    def test_matches_the_shared_cases(self, value: str, expected: str) -> None:
        # ``fallback=""`` because the fallback is this side's alone — the
        # browser leaves the field empty and lets the server substitute.
        assert slugify(value, fallback="", max_length=_FIXTURE["max_length"]) == expected


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


class TestSuffixed:
    """The candidate shape both slug rules share.

    ``news.content._slugs.free_slug`` had its own copy of this loop, and the two
    had already drifted on the cap and the failure mode. The truncation is the
    half that must not drift: ``free_slug`` prefilters the taken set by a stem,
    which is only sound while every candidate keeps starting with the same cut.
    """

    def test_the_suffix_fits_inside_the_limit_rather_than_past_it(self) -> None:
        candidates = list(suffixed("a" * 10, max_length=10, limit=3))

        assert candidates == ["a" * 8 + "-2", "a" * 8 + "-3"]

    def test_it_stops_at_the_limit(self) -> None:
        assert list(suffixed("x", max_length=10, limit=2)) == ["x-2"]

    def test_a_wider_suffix_eats_more_of_the_base(self) -> None:
        # ``-10`` is one character longer than ``-9``, so the stem shortens.
        wide = list(suffixed("a" * 10, max_length=10, limit=10))[-1]

        assert wide == "a" * 7 + "-10"
        assert len(wide) == 10

    def test_the_articles_stem_prefilter_still_covers_every_candidate(self) -> None:
        """What ``_stem_length`` promises, stated against the shared generator.

        A base already at ``MAX_SLUG_LEN`` is cut to make room for the suffix,
        so ``startswith(base)`` would miss its variants entirely — the stem is
        the prefix they all keep.
        """
        from news.content._slugs import _stem_length

        base = "a" * MAX_SLUG_LEN
        stem = base[: _stem_length(base)]

        assert all(
            c.startswith(stem)
            for c in suffixed(
                base, max_length=MAX_SLUG_LEN, limit=MAX_SLUG_ATTEMPTS + 1
            )
        )
