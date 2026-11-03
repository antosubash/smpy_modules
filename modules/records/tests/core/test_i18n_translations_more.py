"""test_i18n_translations cases."""

from __future__ import annotations

from sm_records.core.settings import RecordsSettings

from tests.support.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, roles
from tests.support.i18n_helpers import (
    API,
    TYPE_KEY,
    make_record,
    make_type,
    set_type,
    translate,
)


async def test_the_refusals(bilingual):
    """A locale that is not configured, the source's own locale, a sibling
    that already holds the language, and a type that is not translatable."""
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")

    bad_locale = await translate(bilingual, record["uuid"], "fr")
    assert bad_locale.status_code == 422 and "'fr'" in bad_locale.text

    same = await translate(bilingual, record["uuid"], "en")
    assert same.status_code == 409 and "already in 'en'" in same.text

    assert (await translate(bilingual, record["uuid"], "de")).status_code == 201
    second = await translate(bilingual, record["uuid"], "de")
    assert second.status_code == 409 and "already exists" in second.text


async def test_a_trashed_sibling_still_blocks_the_language(bilingual):
    """It keeps its slug claim and its row in the unique index until it is
    purged or restored, so offering to create a second would only ever 409."""
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    sibling = (await translate(bilingual, record["uuid"], "de")).json()
    gone = await bilingual.delete(
        f"{API}/{TYPE_KEY}/records/{sibling['uuid']}", headers=roles(ADMIN)
    )
    assert gone.status_code == 204

    again = await translate(bilingual, record["uuid"], "de")
    assert again.status_code == 409
    assert "in the trash" in again.text
    # And the source is untouched: a group is a grouping, not a cascade.
    still = await bilingual.get(f"{API}/{TYPE_KEY}/records/{record['uuid']}", headers=roles(ADMIN))
    assert still.status_code == 200 and still.json()["is_deleted"] is False


async def test_a_non_translatable_type_refuses_translations(bilingual):
    await make_type(bilingual, translatable=False)
    record = await make_record(bilingual, "About us")
    resp = await translate(bilingual, record["uuid"], "de")
    assert resp.status_code == 409, resp.text
    assert "not translatable" in resp.text


async def test_listing_a_group_includes_the_record_itself_and_its_trash(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    sibling = (await translate(bilingual, record["uuid"], "de")).json()
    await bilingual.delete(f"{API}/{TYPE_KEY}/records/{sibling['uuid']}", headers=roles(ADMIN))

    listed = await bilingual.get(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}/translations", headers=roles(ADMIN)
    )
    assert listed.status_code == 200, listed.text
    by_locale = {item["locale"]: item for item in listed.json()}
    assert set(by_locale) == {"en", "de"}
    assert by_locale["en"]["uuid"] == record["uuid"]
    assert by_locale["en"]["is_deleted"] is False
    assert by_locale["de"]["is_deleted"] is True


async def test_translations_are_opt_in_on_the_read_and_never_on_the_list(bilingual):
    await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    await translate(bilingual, record["uuid"], "de")

    plain = await bilingual.get(f"{API}/{TYPE_KEY}/records/{record['uuid']}", headers=roles(ADMIN))
    assert plain.json()["translations"] is None

    asked = await bilingual.get(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}?translations=true", headers=roles(ADMIN)
    )
    assert [item["locale"] for item in asked.json()["translations"]] == ["de", "en"]

    listed = await bilingual.get(f"{API}/{TYPE_KEY}/records", headers=roles(ADMIN))
    assert all(item["translations"] is None for item in listed.json()["items"])


async def test_the_list_filters_and_sorts_by_locale_and_defaults_to_all(bilingual):
    await make_type(bilingual)
    await make_record(bilingual, "About us", locale="en")
    await make_record(bilingual, "Über uns", locale="de")

    every = await bilingual.get(f"{API}/{TYPE_KEY}/records", headers=roles(ADMIN))
    # No default locale filter anywhere: an editor's question is "what
    # exists", not "what exists in English" (§4.4).
    assert {item["locale"] for item in every.json()["items"]} == {"en", "de"}

    german = await bilingual.get(
        f"{API}/{TYPE_KEY}/records?filter=locale:eq:de", headers=roles(ADMIN)
    )
    assert [item["locale"] for item in german.json()["items"]] == ["de"]

    sorted_ = await bilingual.get(f"{API}/{TYPE_KEY}/records?sort=locale", headers=roles(ADMIN))
    assert [item["locale"] for item in sorted_.json()["items"]] == ["de", "en"]

    # And a cursor taken under that sort resumes from it: ``locale`` needs a
    # cursor decoder like every other fixed column, or page two is a 500.
    first = await bilingual.get(
        f"{API}/{TYPE_KEY}/records?sort=locale&page_size=1", headers=roles(ADMIN)
    )
    second = await bilingual.get(
        f"{API}/{TYPE_KEY}/records?sort=locale&page_size=1&after={first.json()['next_cursor']}",
        headers=roles(ADMIN),
    )
    assert second.status_code == 200, second.text
    assert [item["locale"] for item in second.json()["items"]] == ["en"]


async def test_translatable_cannot_be_turned_off_while_foreign_records_exist(bilingual):
    rtype = await make_type(bilingual)
    record = await make_record(bilingual, "About us")
    await translate(bilingual, record["uuid"], "de")

    rtype = (await bilingual.get(f"{API}/{TYPE_KEY}", headers=roles(ADMIN))).json()
    refused = await set_type(bilingual, rtype, translatable=False)
    assert refused.status_code == 409, refused.text
    assert "other than 'en'" in refused.text

    # Turning it *on* is always fine — every existing record already carries
    # the default locale, and nothing about them changes.
    assert (await set_type(bilingual, rtype, translatable=True)).status_code == 200


async def test_allowed_roles_narrow_translation_creation(bilingual):
    """Creating a translation is creating a record, so the type's own
    ``allowed_roles`` narrow it exactly as they narrow every other write."""
    await make_type(bilingual, allowed_roles=[ROLE_EDITOR])
    record = await make_record(bilingual, "About us", actor=ROLE_EDITOR)

    refused = await translate(bilingual, record["uuid"], "de", actor=ROLE_EDITOR_TWO)
    assert refused.status_code == 403, refused.text
    assert (await translate(bilingual, record["uuid"], "de", actor=ROLE_EDITOR)).status_code == 201


async def test_a_single_locale_install_behaves_exactly_as_before(client):
    """The acceptance test for "inert when unused": with one content locale
    nothing can name another one, and every record is in it."""
    assert client.app.state.sm_records.settings.content_locales == RecordsSettings().content_locales
    await make_type(client, translatable=False)
    record = await make_record(client, "About us")
    assert record["locale"] == "en"
    assert (await translate(client, record["uuid"], "de")).status_code == 409
