"""``ImportTargets.tag_choices``: the ``tags`` choices an import decides its values against,
indexed field or not (newsletter PR 7, ruling T6b)."""

from __future__ import annotations

from sm_records.contracts.newsletter_admin import list_fields
from sm_records.contracts.newsletter_import import importable_fields
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.records.services import types as type_service

from tests.support.app_harness import field
from tests.support.newsletter_contract import TENANT, session, unbound


async def _list(site, key: str, fields: list[dict]) -> None:
    async with session(site) as db:
        with tenant_scope(TENANT):
            await type_service.create_type(
                db,
                key=key,
                label=key,
                fields_raw=fields,
                public_submissions={"kind": "subscription"},
                settings=RecordsSettings(),
            )
            await events.commit(db)


async def test_tag_choices_of_a_non_indexed_tags_field(site):
    choices = [{"value": "VIP", "label": "Very important"}]
    await _list(site, "plain", [field("tags", "multiselect", indexed=False, choices=choices)])
    async with session(site) as db:
        with unbound():
            targets = await importable_fields(db, tenant_id=TENANT, type_key="plain")
            listed = await list_fields(db, tenant_id=TENANT, type_key="plain")
    assert targets is not None and targets.tags == "present"
    assert [(c.value, c.label) for c in targets.tag_choices] == [("VIP", "Very important")]
    assert "tags" not in [f.key for f in listed]  # what the indexed-only read saw


async def test_tag_choices_empty_without_a_multiselect(site):
    await _list(site, "notags", [field("first_name")])
    await _list(site, "texttags", [field("tags")])
    async with session(site) as db:
        with unbound():
            none = await importable_fields(db, tenant_id=TENANT, type_key="notags")
            text = await importable_fields(db, tenant_id=TENANT, type_key="texttags")
    assert none is not None and none.tag_choices == [] and none.tags == "creatable"
    assert text is not None and text.tag_choices == [] and text.tags == "missing"
