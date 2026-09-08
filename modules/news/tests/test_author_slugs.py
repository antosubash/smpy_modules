"""How a byline becomes an address. Sync tests, so deliberately not under the
asyncio mark — the same reason ``test_slugify.py`` sits on its own.

The rule itself is ``news.slugify``'s, shared with categories and tags; what is
pinned here is the *one* thing the author derivation adds to it, and the one
thing that would be a silent data loss if it drifted: a byline with nothing to
slugify has no address at all rather than the slugifier's fallback, which every
such byline would share.
"""

from __future__ import annotations

from news.authors import slug_for


class TestSlugFor:
    def test_it_is_the_module_wide_slug_rule(self) -> None:
        assert slug_for("Anto Subash") == "anto-subash"

    def test_accents_fold_rather_than_dropping(self) -> None:
        # A third slug rule would be a third thing that can drift; this is the
        # same folding a category gets.
        assert slug_for("Étude Dupont") == "etude-dupont"

    def test_two_spellings_collide_on_purpose(self) -> None:
        """One address for both, which is what makes the page correct.

        A byline entered two ways is overwhelmingly one person entered
        inconsistently, and the archive lists the articles under either.
        """
        assert slug_for("A. Subash") == slug_for("A Subash")

    def test_a_byline_that_transliterates_to_nothing_has_no_address(self) -> None:
        """``""``, not the slugifier's fallback.

        With a fallback every such byline would share one slug, and a single
        archive page would claim to be several unrelated people. Empty means
        "not addressable", and the viewer then renders the byline as text.
        """
        assert slug_for("田中太郎") == ""
        assert slug_for("") == ""
