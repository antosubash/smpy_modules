"""Snapshots of a site that publishes in more than one language.

A bundle used to identify a page by its slug alone. That stopped being an
identity the moment ``(locale, slug)`` became the unique index: an English and
a German page may both be ``about``, and every map keyed by the bare slug
silently kept whichever came last. These tests pin the pair down at each layer
the bundle passes through — capture, validate, plan, apply — because the
failure mode is a lost page rather than an error.
"""

from __future__ import annotations

import json

import pytest
from pagebuilder.models import Page, PageRedirect, PageStatus
from pagebuilder.snapshots.apply import apply_bundle
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.capture import capture, page_filename
from pagebuilder.snapshots.pages import payload_locale
from pagebuilder.snapshots.plan import read_pages
from sqlalchemy import delete
from sqlmodel import select

pytestmark = pytest.mark.asyncio

GROUP = "grp-about"


async def _capture(db, tmp_path, name="bundle"):
    dest = tmp_path / name
    blobs = BlobStore(tmp_path / "blobs")
    result = await capture(db.session, db.settings, dest, blobs)
    return dest, result


async def _about_in_both(session) -> None:
    """One document, two languages, one slug — the case that used to collide."""
    session.add(
        Page(
            slug="about",
            locale="en",
            translation_group=GROUP,
            title="About us",
            status=PageStatus.PUBLISHED,
        )
    )
    session.add(
        Page(
            slug="about",
            locale="de",
            translation_group=GROUP,
            title="Über uns",
            status=PageStatus.PUBLISHED,
        )
    )
    await session.flush()


async def test_one_slug_in_two_languages_survives_capture(
    bilingual_snapshot_db, tmp_path
):
    await _about_in_both(bilingual_snapshot_db.session)
    dest, result = await _capture(bilingual_snapshot_db, tmp_path)

    # Two documents, not one overwriting the other.
    written = sorted(p.name for p in (dest / "pages").glob("*.json"))
    assert written == ["about.json", "de__about.json"]

    titles = {(e["locale"], e["title"]) for e in result.manifest["pages"]}
    assert titles == {("en", "About us"), ("de", "Über uns")}


async def test_the_default_locale_keeps_its_bare_filename():
    """A monolingual site's bundle is byte-for-byte what earlier builds wrote."""
    assert page_filename("about", "en") == "about.json"
    assert page_filename("about", "de") == "de__about.json"


async def test_a_separator_in_either_half_cannot_escape_the_directory():
    assert "/" not in page_filename("a/b", "de")
    assert page_filename("a/b", "de").startswith("de__")


async def test_read_pages_keeps_both_languages(bilingual_snapshot_db, tmp_path):
    await _about_in_both(bilingual_snapshot_db.session)
    dest, _ = await _capture(bilingual_snapshot_db, tmp_path)

    pages = read_pages(dest)
    assert set(pages) == {("en", "about"), ("de", "about")}
    assert pages[("de", "about")]["title"] == "Über uns"


async def test_capture_carries_locale_and_translation_group(
    bilingual_snapshot_db, tmp_path
):
    """Dropped, a restored site holds translations it can no longer link up."""
    await _about_in_both(bilingual_snapshot_db.session)
    dest, _ = await _capture(bilingual_snapshot_db, tmp_path)

    german = json.loads((dest / "pages" / "de__about.json").read_text())
    assert german["locale"] == "de"
    assert german["translation_group"] == GROUP


async def test_a_version_1_document_reads_as_the_default_locale():
    """Bundles written before the column came from a single-language site."""
    assert payload_locale({"slug": "about"}) == "en"


async def test_a_locale_this_host_does_not_publish_is_kept_verbatim():
    """Inert, but preserved.

    Nothing routes ``/fr/p/…`` until ``fr`` is configured — but folding those
    pages into the default locale would collide every one of them with its
    English counterpart and overwrite it. Keeping the tag loses nothing and
    lights the pages up the moment the language is added.
    """
    assert payload_locale({"slug": "about", "locale": "fr"}) == "fr"


async def test_a_malformed_locale_reads_as_the_default():
    """`normalise_locale` stays total; `validate` is what refuses the bundle."""
    assert payload_locale({"slug": "about", "locale": "../etc"}) == "en"
    assert payload_locale({"slug": "about", "locale": 7}) == "en"


async def test_redirects_are_captured_per_language(bilingual_snapshot_db, tmp_path):
    """The same retired address can exist in two languages, pointing at two
    different pages — ``(locale, from_slug)`` is what is unique."""
    session = bilingual_snapshot_db.session
    await _about_in_both(session)
    english = (
        await session.execute(select(Page).where(Page.locale == "en"))
    ).scalars().first()
    german = (
        await session.execute(select(Page).where(Page.locale == "de"))
    ).scalars().first()
    session.add(PageRedirect(from_slug="info", locale="en", page_id=english.id))
    session.add(PageRedirect(from_slug="info", locale="de", page_id=german.id))
    await session.flush()

    dest, _ = await _capture(bilingual_snapshot_db, tmp_path)
    rows = json.loads((dest / "redirects.json").read_text())
    assert sorted((r["locale"], r["from_slug"]) for r in rows) == [
        ("de", "info"),
        ("en", "info"),
    ]


async def _round_trip(db, tmp_path):
    """Capture the site, wipe its pages, and restore the bundle onto the same db.

    Wiping between the two halves is what makes this a restore rather than an
    update: the pages have to be *created* from the bundle, which is the path
    that has to get ``locale`` right — an update would inherit it from the row
    already there and pass even if the bundle carried nothing.
    """
    dest, _ = await _capture(db, tmp_path)
    await db.session.execute(delete(PageRedirect))
    await db.session.execute(delete(Page))
    await db.session.flush()
    blobs = BlobStore(tmp_path / "blobs")
    return await apply_bundle(db.session, db.settings, dest, blobs, {})


async def test_a_bilingual_site_round_trips(bilingual_snapshot_db, tmp_path):
    session = bilingual_snapshot_db.session
    await _about_in_both(session)

    summary = await _round_trip(bilingual_snapshot_db, tmp_path)
    assert summary["pages_created"] == 2

    restored = (await session.execute(select(Page))).scalars().all()
    assert {(p.locale, p.slug, p.title) for p in restored} == {
        ("en", "about", "About us"),
        ("de", "about", "Über uns"),
    }
    # One document in two languages, still linked as one document.
    assert {p.translation_group for p in restored} == {GROUP}


async def test_restoring_does_not_overwrite_one_language_with_another(
    bilingual_snapshot_db, tmp_path
):
    """The failure this whole change exists to prevent.

    Keyed by the bare slug, the German document would land on the English row
    — the site would end up with one page holding the other's words, and the
    restore would report success.
    """
    session = bilingual_snapshot_db.session
    await _about_in_both(session)
    dest, _ = await _capture(bilingual_snapshot_db, tmp_path)

    blobs = BlobStore(tmp_path / "blobs")
    summary = await apply_bundle(session, bilingual_snapshot_db.settings, dest, blobs, {})

    # Both matched existing rows; nothing was created, nothing crossed over.
    assert (summary["pages_created"], summary["pages_updated"]) == (0, 2)
    english = (
        await session.execute(select(Page).where(Page.locale == "en"))
    ).scalars().one()
    german = (
        await session.execute(select(Page).where(Page.locale == "de"))
    ).scalars().one()
    assert english.title == "About us"
    assert german.title == "Über uns"


async def test_a_redirect_resolves_within_its_own_language(
    bilingual_snapshot_db, tmp_path
):
    """A retired English address must not start serving the German page that
    happens to use the slug it pointed at."""
    session = bilingual_snapshot_db.session
    await _about_in_both(session)
    english = (
        await session.execute(select(Page).where(Page.locale == "en"))
    ).scalars().one()
    german = (
        await session.execute(select(Page).where(Page.locale == "de"))
    ).scalars().one()
    session.add(PageRedirect(from_slug="info", locale="en", page_id=english.id))
    session.add(PageRedirect(from_slug="info", locale="de", page_id=german.id))
    await session.flush()

    await _round_trip(bilingual_snapshot_db, tmp_path)

    rows = (await session.execute(select(PageRedirect))).scalars().all()
    by_locale = {r.locale: r for r in rows}
    assert set(by_locale) == {"en", "de"}
    pages = {
        p.id: p.locale for p in (await session.execute(select(Page))).scalars().all()
    }
    # Each redirect points at the page in its own language.
    assert pages[by_locale["en"].page_id] == "en"
    assert pages[by_locale["de"].page_id] == "de"
