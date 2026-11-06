"""The newsletter import contract's list creation, mapping targets and tag
choices (newsletter PR 7, task 1)."""

from __future__ import annotations

from typing import Any

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records.contracts.newsletter import count_subscribers, subscription_lists
from sm_records.contracts.newsletter_admin import FieldChoice, list_fields
from sm_records.contracts.newsletter_import import (
    ImportTargets,
    InvalidListKey,
    ListExists,
    SubscriberFilterError,
    TagsFieldMissing,
    add_tag_choices,
    create_list,
    importable_fields,
)
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import RecordType
from sm_records.records.services import types as type_service
from sqlalchemy import select

from tests.support.app_harness import field
from tests.support.newsletter_contract import TENANT, seed_list, session, unbound
from tests.support.newsletter_http import LIST

SETTINGS = RecordsSettings()


def _c(*values: str) -> list[FieldChoice]:
    return [FieldChoice(value=v, label=v.upper()) for v in values]


async def _make(site, tenant: str = TENANT, key: str = "weekly") -> str:
    async with session(site) as db:
        with unbound():
            made = await create_list(
                db, tenant_id=tenant, key=key, label="Weekly", settings=SETTINGS
            )
            await events.commit(db)
    return made


async def _tag_values(site, key: str = "weekly") -> list[str]:
    async with session(site) as db:
        with unbound():
            fields = await list_fields(db, tenant_id=TENANT, type_key=key)
    return [c.value for f in fields if f.key == "tags" for c in f.choices]


async def _version(site, key: str = "weekly") -> int:
    async with session(site) as db:
        with tenant_scope(TENANT):
            rtype = (await db.execute(select(RecordType).where(RecordType.key == key))).scalar_one()
            return rtype.version


async def _targets(site, key: str = "weekly", tenant: str = TENANT) -> ImportTargets | None:
    async with session(site) as db:
        with unbound():
            return await importable_fields(db, tenant_id=tenant, type_key=key)


async def _add(site, choices, key: str = "weekly", tenant: str = TENANT) -> list[str]:
    async with session(site) as db:
        with unbound():
            added = await add_tag_choices(
                db,
                tenant_id=tenant,
                type_key=key,
                choices=choices,
                settings=SETTINGS,
            )
            await events.commit(db)
    return added


async def test_create_list_is_a_subscription_list_with_names(site):
    assert await _make(site) == "weekly"
    async with session(site) as db:
        with unbound():
            assert "weekly" in await subscription_lists(db, tenant_id=TENANT)
    targets = await _targets(site)
    assert targets is not None
    assert [f.key for f in targets.fields] == ["first_name", "last_name"]
    assert targets.tags == "creatable"
    async with session(site) as db:
        with tenant_scope(TENANT):
            rtype = (
                await db.execute(select(RecordType).where(RecordType.key == "weekly"))
            ).scalar_one()
            config: dict[str, Any] = rtype.public_submissions
            assert rtype.show_in_menu is True
    assert config["double_opt_in"] is True
    assert config["enabled"] is False


async def test_create_list_twice_raises_list_exists(site):
    await _make(site)
    with pytest.raises(ListExists):
        await _make(site)


async def test_create_list_bad_key_raises_invalid_list_key(site):
    with pytest.raises(InvalidListKey):
        await _make(site, key="Bad Key")


async def test_importable_fields_skips_system_tags_and_unmappable(site):
    fields = [
        field("first_name", indexed=False),
        field("last_name", indexed=False),
        field("tags", "multiselect", choices=[{"value": "a", "label": "A"}]),
        field("age", "integer"),
        field("team", "select", choices=[{"value": "x", "label": "X"}]),
    ]
    async with session(site) as db:
        with tenant_scope(TENANT):
            await type_service.create_type(
                db,
                key="mixed",
                label="Mixed",
                fields_raw=fields,
                public_submissions={"kind": "subscription"},
                settings=SETTINGS,
            )
            await events.commit(db)
    targets = await _targets(site, "mixed")
    assert targets is not None
    assert [f.key for f in targets.fields] == ["first_name", "last_name", "team"]
    team = targets.fields[2]
    assert team.type == "select"
    assert [(c.value, c.label) for c in team.choices] == [("x", "X")]
    assert targets.tags == "present"


async def test_importable_fields_unknown_is_none_and_form_raises(site):
    assert await _targets(site, "nope") is None
    async with session(site) as db:
        with tenant_scope(TENANT):
            await type_service.create_type(
                db,
                key="contact",
                label="Contact",
                fields_raw=[field("name")],
                public_submissions={"kind": "form"},
                settings=SETTINGS,
            )
            await events.commit(db)
    with pytest.raises(SubscriberFilterError) as err:
        await _targets(site, "contact")
    assert err.value.reason == "not_a_list"


async def test_add_tag_choices_appends_once(site):
    await _make(site)
    assert await _add(site, _c("a", "b")) == ["a", "b"]
    renamed = [FieldChoice(value="b", label="Other"), FieldChoice(value="c", label="C")]
    assert await _add(site, renamed) == ["c"]
    assert await _tag_values(site) == ["a", "b", "c"]
    async with session(site) as db:
        with unbound():
            fields = await list_fields(db, tenant_id=TENANT, type_key="weekly")
    tags = next(f for f in fields if f.key == "tags")
    assert {c.value: c.label for c in tags.choices} == {"a": "A", "b": "B", "c": "C"}
    version = await _version(site)
    assert await _add(site, _c("a")) == []
    assert await _version(site) == version


async def test_add_tag_choices_creates_field_on_empty_list(site):
    await _make(site)
    await _add(site, _c("a"))
    async with session(site) as db:
        with unbound():
            fields = await list_fields(db, tenant_id=TENANT, type_key="weekly")
            tags = next(f for f in fields if f.key == "tags")
            assert tags.many is True
            assert (
                await count_subscribers(
                    db, tenant_id=TENANT, type_key="weekly", filters=["tags:eq:a"]
                )
                == 0
            )
    assert (await _targets(site)).tags == "present"


async def test_add_tag_choices_refuses_populated_list_without_field(site):
    await seed_list(site.db_state, TENANT, "ada@example.org")  # fields: first_name + tags
    # a list without tags but with a subscriber
    from sm_records.records.services import records as record_service
    from sm_records.records.services._common import utcnow

    with tenant_scope(TENANT):
        async with site.db_state.session_factory() as db:
            rtype = await type_service.create_type(
                db,
                key="weekly",
                label="Weekly",
                public_submissions={"kind": "subscription"},
                settings=SETTINGS,
            )
            await record_service.create_record(
                db,
                rtype,
                data={},
                settings=SETTINGS,
                system={
                    "sm_email": "x@example.org",
                    "sm_status": "confirmed",
                    "sm_confirmed_at": utcnow(),
                    "sm_locale": "en",
                    "sm_nonce": "0" * 32,
                },
            )
            await events.commit(db)
    before = await _version(site)
    with pytest.raises(TagsFieldMissing):
        await _add(site, _c("a"))
    assert await _version(site) == before
    assert (await _targets(site)).tags == "missing"


@pytest.mark.parametrize(
    "choices",
    [
        [FieldChoice(value=f"v{i}", label="x") for i in range(501)],
        [FieldChoice(value="", label="x")],
        [FieldChoice(value="a", label="l" * 101)],
        [FieldChoice(value="a\x00", label="x")],
        [FieldChoice(value="a", label="x"), FieldChoice(value="a", label="y")],
    ],
    ids=["too_many", "empty_value", "long_label", "nul", "duplicate"],
)
async def test_add_tag_choices_validates(site, choices):
    await _make(site)
    before = await _version(site)
    with pytest.raises(ValueError):
        await _add(site, choices)
    assert await _version(site) == before
    assert await _tag_values(site) == []


async def test_import_lists_pin_the_tenant(site):
    with unbound():
        await seed_list(site.db_state, "other", "ada@example.org")
    assert await _targets(site, LIST, tenant="other") is not None
    assert await _targets(site, LIST, tenant=TENANT) is None
    assert await _make(site, key=LIST) == LIST


async def test_bound_other_tenant_raises(site):
    async with session(site) as db:
        with tenant_scope(TENANT), pytest.raises(TenantIsolationError):
            await importable_fields(db, tenant_id="other", type_key="weekly")
        with tenant_scope(TENANT), pytest.raises(TenantIsolationError):
            await create_list(db, tenant_id="other", key="k", label="K", settings=SETTINGS)
