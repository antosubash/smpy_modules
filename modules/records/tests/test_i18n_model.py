"""The columns, the indexes and the settings content i18n rests on (§4.1/§4.2).

Everything here is below HTTP: the unique index that makes a slug an address
*within a language*, the translation group a record is alone in until it is
not, and the configured locale list the rest of the module reads.

The load-bearing one is
:func:`test_the_same_slug_is_free_in_every_other_locale` and its twin
:func:`test_a_slug_is_still_unique_within_one_locale`. Together they are the
difference between this feature and the half-version the original design
warned about — a record with a locale whose slug is not scoped to it, which is
how ``?locale=de`` starts serving the English record.
"""

from __future__ import annotations

import pytest
from sm_records import locales
from sm_records.constants import RESERVED_FIELD_KEYS
from sm_records.models import Record, RecordType
from sm_records.settings import RecordsSettings
from sqlalchemy.exc import IntegrityError


async def _article_type(db) -> RecordType:
    rtype = RecordType(key="article", label="Article", label_plural="Articles", fields=[])
    db.add(rtype)
    await db.flush()
    return rtype


async def _record(db, rtype: RecordType, **cols) -> Record:
    record = Record(type_id=rtype.id, data={}, schema_version=rtype.schema_version, **cols)
    db.add(record)
    await db.flush()
    return record


async def test_a_record_defaults_to_english_and_its_own_group(db):
    """The column defaults, which every row written before this feature has.

    ``translation_group`` defaults to a fresh key rather than to ``uuid``
    here — the model has no way to make two ``default_factory`` calls agree.
    ``create_record`` is what ties them together, and
    ``test_create_record_puts_a_record_in_its_own_group`` asserts that.
    """
    rtype = await _article_type(db)
    record = await _record(db, rtype)
    assert record.locale == "en"
    assert record.translation_group
    assert len(record.translation_group) == 32


async def test_the_same_slug_is_free_in_every_other_locale(db):
    """§4.1's whole point: ``(type_id, locale, slug)``, not ``(type_id, slug)``.

    The same word is a legal address in English and in German, because they
    are two documents at two addresses — and forcing the German one to pick a
    different word would make the URL a workaround for a schema decision.
    """
    rtype = await _article_type(db)
    await _record(db, rtype, slug="about", locale="en")
    await _record(db, rtype, slug="about", locale="de")
    await _record(db, rtype, slug="about", locale="fr")


async def test_a_slug_is_still_unique_within_one_locale(db):
    rtype = await _article_type(db)
    await _record(db, rtype, slug="about", locale="de")
    with pytest.raises(IntegrityError):
        await _record(db, rtype, slug="about", locale="de")


async def test_the_partial_predicate_survives_the_new_column_list(db):
    """``WHERE slug IS NOT NULL`` — many records may have no slug at all, and
    the index has to keep letting them. Autogenerate never compares an index's
    ``WHERE``, so this is the only thing that would notice it being lost."""
    rtype = await _article_type(db)
    for _ in range(3):
        await _record(db, rtype, slug=None, locale="de")


async def test_one_record_per_language_per_group(db):
    """A second "add German" — a double submit, a stale tab, two rows of an
    import sharing a group — must not produce two German siblings."""
    rtype = await _article_type(db)
    first = await _record(db, rtype, locale="en", slug="a")
    await _record(db, rtype, locale="de", slug="b", translation_group=first.translation_group)
    with pytest.raises(IntegrityError):
        await _record(db, rtype, locale="de", slug="c", translation_group=first.translation_group)


async def test_a_trashed_sibling_keeps_its_language(db):
    """The unique index is on the row, not on live rows — the language is
    occupied until the record is purged or restored, exactly as its slug is."""
    rtype = await _article_type(db)
    first = await _record(db, rtype, locale="en", slug="a")
    trashed = await _record(
        db, rtype, locale="de", slug="b", translation_group=first.translation_group
    )
    trashed.is_deleted = True
    db.add(trashed)
    await db.flush()
    with pytest.raises(IntegrityError):
        await _record(db, rtype, locale="de", slug="c", translation_group=first.translation_group)


def test_the_two_new_columns_are_reserved_field_keys():
    """Derived from the model, never hand-typed: the query layer resolves a
    fixed column *before* a type's own fields, so a field keyed ``locale``
    would index correctly and then be answered from ``records_record``."""
    assert {"locale", "translation_group"} <= RESERVED_FIELD_KEYS


def test_locale_is_a_filterable_sortable_fixed_column():
    from sm_records.index.query import FIXED_COLUMNS

    assert "locale" in FIXED_COLUMNS


def test_settings_refuse_an_empty_list_a_stray_default_and_a_bad_tag():
    with pytest.raises(ValueError, match="at least one locale"):
        RecordsSettings(content_locales=())
    with pytest.raises(ValueError, match="not in"):
        RecordsSettings(content_locales=("en", "de"), default_content_locale="fr")
    with pytest.raises(ValueError, match="language tags"):
        # Uppercase is refused on the *configured* list even though resolution
        # is case-insensitive: two spellings of one language must not be able
        # to address two different sets.
        RecordsSettings(content_locales=("EN",))


def test_resolve_is_case_insensitive_and_returns_the_configured_spelling():
    settings = RecordsSettings(content_locales=("en", "pt-br"))
    assert locales.resolve(settings, "PT-BR") == "pt-br"
    assert locales.resolve(settings, " pt-br ") == "pt-br"
    assert locales.resolve(settings, "fr") is None
    assert locales.resolve(settings, None) is None


def test_require_defaults_when_nothing_was_asked_for_and_names_what_it_refuses():
    from sm_records.services.errors import ValidationFailed

    settings = RecordsSettings(content_locales=("en", "de"))
    assert locales.require(settings, None) == "en"
    with pytest.raises(ValidationFailed) as exc:
        locales.require(settings, "fr")
    assert "'fr'" in exc.value.detail
    assert "en, de" in exc.value.detail
