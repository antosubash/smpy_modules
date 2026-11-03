"""Creating and listing a record's counterparts in other languages (§4.3).

Every rule the addendum states about a translation is here: what it copies,
what it refuses, and the one thing it is not — a way to change a record's
language, which nothing anywhere can do.

The suite runs against a two-locale install configured per test
(``i18n_helpers.use_locales``), because a one-locale install is the *other*
half of the contract and is checked in
:func:`test_a_non_translatable_type_takes_only_the_default_locale` and in
``test_i18n_public``.
"""

from __future__ import annotations

from sm_records.core.settings import RecordsSettings

from tests.support.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, roles
from tests.support.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, set_type, translate


async def test_a_new_record_is_in_the_default_locale_and_alone_in_its_group(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    assert record["locale"] == "en"
    # The group is the record's own uuid: a record with no siblings is alone
    # in a group named after itself (§4.1).
    assert record["translation_group"] == record["uuid"]


async def test_a_create_may_name_a_content_locale(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "Über uns", locale="de")
    assert record["locale"] == "de"


async def test_a_create_naming_an_unconfigured_locale_is_a_422_naming_it(bilingual):
    await make_type(bilingual)
    resp = await bilingual.post(
        f"{API}/{TYPE_KEY}/records",
        json={"data": {"title": "Bonjour"}, "locale": "fr"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert "'fr'" in resp.text
    assert "en, de" in resp.text


async def test_a_non_translatable_type_takes_only_the_default_locale(bilingual):
    """Off by default is what keeps content i18n inert: a record written into
    a language its type does not offer would be reachable by uuid and by
    nothing else."""
    await make_type(bilingual, translatable=False)
    resp = await bilingual.post(
        f"{API}/{TYPE_KEY}/records",
        json={"data": {"title": "Über uns"}, "locale": "de"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert "not translatable" in resp.text
    # The default still works, unchanged.
    assert (await make_record(bilingual, "About us", locale="en"))["locale"] == "en"


async def test_a_put_carrying_a_locale_is_refused_rather_than_ignored(bilingual):
    """Declared on ``RecordUpdate`` so it is *refused*, not dropped: a client
    sending back the record it just read would otherwise get a 200 for a
    language change that never happened."""
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    resp = await bilingual.put(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}",
        json={"expected_version": record["version"], "data": record["data"], "locale": "de"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert "fixed for a record's lifetime" in resp.text
    # Even sending the record's *own* locale back is refused — the key is the
    # problem, not the value, because honouring it is never possible.
    same = await bilingual.put(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}",
        json={"expected_version": record["version"], "data": record["data"], "locale": "en"},
        headers=roles(ADMIN),
    )
    assert same.status_code == 422


async def test_a_translation_copies_payload_and_position_but_never_the_status(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us", position=7)
    published = await publish(bilingual, record)
    assert published["status"] == "published"

    resp = await translate(bilingual, record["uuid"], "de")
    assert resp.status_code == 201, resp.text
    sibling = resp.json()
    assert sibling["locale"] == "de"
    assert sibling["translation_group"] == record["translation_group"]
    assert sibling["data"] == published["data"]
    assert sibling["position"] == 7
    # A translation going live the moment it is created would publish
    # untranslated copy at an address that did not exist a second earlier.
    assert sibling["status"] == "draft"
    assert sibling["uuid"] != record["uuid"]


async def test_the_sibling_gets_the_source_slug_because_it_is_free_in_its_own_locale(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    sibling = (await translate(bilingual, record["uuid"], "de")).json()
    assert record["slug"] == "about-us"
    assert sibling["slug"] == "about-us"


async def test_a_taken_slug_in_the_target_locale_is_suffixed_not_inherited(bilingual):
    """Regenerated *in the target locale*, so it never silently inherits an
    address another record there already answers at."""
    await make_type(bilingual)
    await make_record(bilingual, "About us", locale="de")
    record = await make_record(bilingual, "About us", locale="en")
    sibling = (await translate(bilingual, record["uuid"], "de")).json()
    assert sibling["slug"] == "about-us-2"


async def test_an_explicit_slug_is_used_and_refused_if_taken_there(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    ok = await translate(bilingual, record["uuid"], "de", slug="ueber-uns")
    assert ok.status_code == 201
    assert ok.json()["slug"] == "ueber-uns"

    other = await make_record(bilingual, "Contact")
    taken = await translate(bilingual, other["uuid"], "de", slug="ueber-uns")
    assert taken.status_code == 409, taken.text
    assert "'de'" in taken.text
