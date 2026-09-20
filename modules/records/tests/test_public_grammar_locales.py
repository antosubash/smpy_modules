"""What the anonymous read API will answer about, and in which languages.

Three QA findings, all about the same surface being wider than the shape it
publishes:

* a **virtual field** — a key an index provider projects (§7.6) — was
  filterable, sortable, and readable *in clear* out of the ``?after=`` cursor,
  although nothing puts it in ``PublicRecordRead``;
* a record in a locale the install has since dropped from ``content_locales``
  stayed publicly readable by uuid and stayed in the language switcher, while
  the listing refused to name that language at all;
* the cursor signature covered the type, the sort and the trash flag, but
  neither the sort fields' index kinds nor the ``?locale=`` the public listing
  was narrowed to.
"""

from __future__ import annotations

from decimal import Decimal

import pytest_asyncio
from sm_records.index import IndexEntry, IndexKind, VirtualField, register_index_provider

from tests.app_harness import ADMIN, roles
from tests.i18n_helpers import API, TYPE_KEY, field, make_record, make_type, publish, translate
from tests.i18n_helpers import use_locales as _use_locales

PREFIX = "/api/records/public"

_SCORES = {"Alpha": 10, "Bravo": 20, "Charlie": 30}


def _provider(record, rtype):
    """A host-computed score that lives only in the index tables."""
    title = (record.data or {}).get("title")
    if title in _SCORES:
        yield IndexEntry(
            kind=IndexKind.NUMBER, field_key="risk_score", value=Decimal(_SCORES[title])
        )


@pytest_asyncio.fixture
async def scored(client):
    register_index_provider(_provider, fields=[VirtualField("risk_score", IndexKind.NUMBER)])
    await client.app.state.records_module.on_startup(client.app)
    await make_type(client, translatable=False, is_public=True)
    for title in _SCORES:
        await publish(client, await make_record(client, title))
    return client


async def test_the_public_shape_does_not_carry_the_virtual_field(scored):
    page = await scored.get(f"{PREFIX}/{TYPE_KEY}")
    assert page.status_code == 200, page.text
    assert all("risk_score" not in item["data"] for item in page.json()["items"])


async def test_an_anonymous_filter_on_a_virtual_field_is_refused(scored):
    refused = await scored.get(f"{PREFIX}/{TYPE_KEY}?filter=risk_score:gte:20")
    assert refused.status_code == 400, refused.text
    assert "risk_score" in refused.json()["detail"]


async def test_an_anonymous_sort_on_a_virtual_field_is_refused(scored):
    refused = await scored.get(f"{PREFIX}/{TYPE_KEY}?sort=-risk_score&page_size=1")
    assert refused.status_code == 400, refused.text
    assert "risk_score" in refused.json()["detail"]


async def test_a_cursor_minted_on_the_admin_api_cannot_replay_the_virtual_sort(scored):
    """Minted where it is legitimate, replayed where it is not.

    The admin listing resolves the virtual field and hands back a cursor whose
    value tuple contains the score. The public listing refuses the request that
    carries it, so the value never leaves by that door either.
    """
    admin = await scored.get(
        f"{API}/{TYPE_KEY}/records?sort=-risk_score&page_size=1", headers=roles(ADMIN)
    )
    assert admin.status_code == 200, admin.text
    cursor = admin.json()["next_cursor"]
    assert cursor

    refused = await scored.get(f"{PREFIX}/{TYPE_KEY}?sort=-risk_score&after={cursor}")
    assert refused.status_code == 400, refused.text
    assert "risk_score" in refused.json()["detail"]
    # And without naming the sort, the signature no longer matches.
    mismatched = await scored.get(f"{PREFIX}/{TYPE_KEY}?after={cursor}")
    assert mismatched.status_code == 400, mismatched.text


async def test_a_declared_field_is_still_filterable_anonymously(scored):
    """The allow-list is the type's declared keys plus the public fixed
    columns, so nothing a type could have meant is refused."""
    page = await scored.get(f"{PREFIX}/{TYPE_KEY}?filter=title:eq:Alpha")
    assert page.status_code == 200, page.text
    assert [item["display_title"] for item in page.json()["items"]] == ["Alpha"]
    assert (await scored.get(f"{PREFIX}/{TYPE_KEY}?sort=slug")).status_code == 200
    assert (await scored.get(f"{PREFIX}/{TYPE_KEY}?sort=-published_at")).status_code == 200


async def test_a_hidden_fixed_column_is_still_refused(scored):
    for query in ("filter=status:eq:published", "sort=created_at", "sort=position"):
        refused = await scored.get(f"{PREFIX}/{TYPE_KEY}?{query}")
        assert refused.status_code == 400, refused.text


@pytest_asyncio.fixture
async def bilingual(client):
    _use_locales(client, "en", "de")
    await client.app.state.records_module.on_startup(client.app)
    await make_type(client, is_public=True)
    english = await publish(client, await make_record(client, "About us"))
    german = await publish(client, (await translate(client, english["uuid"], "de")).json())
    return client, english, german


async def test_a_decommissioned_locale_is_not_served_publicly(bilingual):
    client, english, german = bilingual
    assert (await client.get(f"{PREFIX}/{TYPE_KEY}/{german['uuid']}")).status_code == 200

    _use_locales(client, "en")

    assert (await client.get(f"{PREFIX}/{TYPE_KEY}?locale=de")).status_code == 400
    assert (await client.get(f"{PREFIX}/{TYPE_KEY}/{german['uuid']}")).status_code == 404
    # Empty, and not ``["en"]``: a host down to one content locale issues no
    # sibling query at all (S1), because the only record such a query could
    # ever return is the one the caller is already reading. What the switcher
    # must not do is offer ``de``, and it does not.
    switcher = await client.get(f"{PREFIX}/{TYPE_KEY}/{english['uuid']}")
    assert switcher.json()["translations"] == []
    page = await client.get(f"{PREFIX}/{TYPE_KEY}")
    assert all(item["translations"] == [] for item in page.json()["items"])


async def test_a_decommissioned_locale_stays_readable_and_editable_in_the_admin(bilingual):
    """An operator has to be able to fix them; that is the whole reason
    dropping a locale is not refused at save."""
    client, _, german = bilingual
    _use_locales(client, "en")

    read = await client.get(f"{API}/{TYPE_KEY}/records/{german['uuid']}", headers=roles(ADMIN))
    assert read.status_code == 200, read.text
    assert read.json()["locale"] == "de"

    edited = await client.put(
        f"{API}/{TYPE_KEY}/records/{german['uuid']}",
        json={"expected_version": read.json()["version"], "data": read.json()["data"]},
        headers=roles(ADMIN),
    )
    assert edited.status_code == 200, edited.text

    listed = await client.get(f"{API}/{TYPE_KEY}/records", headers=roles(ADMIN))
    assert "de" in [item["locale"] for item in listed.json()["items"]]


async def test_the_health_check_counts_orphaned_locales(bilingual):
    from sm_records.health import CHECK_NAME, count_orphaned_locales, stale_reindex_check

    client, _, _ = bilingual
    module = client.app.state.records_module
    settings = _use_locales(client, "en")

    counts = await count_orphaned_locales(module.db, settings)
    assert counts == {"de": 1}

    module.orphaned_locales = counts
    module.settings = settings
    check = stale_reindex_check(module)
    assert check.name == CHECK_NAME
    result = await check.check()
    assert result.status == "degraded"
    assert "orphaned_locales: {de: 1}" in result.detail


async def test_a_public_cursor_does_not_cross_locales(bilingual):
    """The locale is a predicate on the statement rather than a caller filter,
    so it has to be in the signature or a cursor resumes a different listing."""
    client, _, _ = bilingual
    for index in range(3):
        english = await publish(client, await make_record(client, f"En {index}"))
        await publish(client, (await translate(client, english["uuid"], "de")).json())

    first = await client.get(f"{PREFIX}/{TYPE_KEY}?page_size=2&sort=slug")
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    same = await client.get(f"{PREFIX}/{TYPE_KEY}?page_size=2&sort=slug&after={cursor}")
    assert same.status_code == 200, same.text

    crossed = await client.get(
        f"{PREFIX}/{TYPE_KEY}?locale=de&page_size=2&sort=slug&after={cursor}"
    )
    assert crossed.status_code == 400, crossed.text


async def test_a_cursor_does_not_survive_the_sort_field_being_retyped(client):
    """The values in a cursor are decoded by the sort term's *kind*, so a
    retype between two pages would compare a decimal against a string."""
    made = await client.post(
        API,
        json={
            "key": "thing",
            "label": "Thing",
            "fields": [field("title", "text"), field("rank", "number")],
            "display_field": "title",
        },
        headers=roles(ADMIN),
    )
    assert made.status_code == 201, made.text
    for index in range(4):
        row = await client.post(
            f"{API}/thing/records",
            json={"data": {"title": f"T{index}", "rank": str(index)}},
            headers=roles(ADMIN),
        )
        assert row.status_code == 201, row.text

    first = await client.get(f"{API}/thing/records?page_size=2&sort=rank", headers=roles(ADMIN))
    cursor = first.json()["next_cursor"]
    assert cursor

    retyped = await client.put(
        f"{API}/thing",
        json={
            "expected_version": made.json()["version"],
            "fields": [field("title", "text"), field("rank", "text")],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert retyped.status_code == 200, retyped.text

    replayed = await client.get(
        f"{API}/thing/records?page_size=2&sort=rank&after={cursor}", headers=roles(ADMIN)
    )
    assert replayed.status_code == 400, replayed.text
