"""Index-provider index_provider_registry cases."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from sm_records.index import (
    IndexEntry,
    IndexKind,
    VirtualField,
    register_index_provider,
    virtual_fields,
)
from sm_records.models import IndexNumber, IndexText
from sm_records.records.index import providers as providers_registry
from sm_records.records.index.writer import write_index
from sm_records.schema.fields import FieldSchemaError, validate_fields

from tests.support.index_providers_cases import (
    BUCKET,
    TAGS_UPPER,
    VIRTUAL_FIELDS,
    broken_provider,
    rows,
    sample_provider,
)
from tests.support.index_providers_cases import catalogue as catalogue
from tests.support.index_providers_cases import registered as registered


class TestRegistry:
    def test_two_providers_claiming_one_key_is_a_value_error(self, registered):
        def other_provider(record, rtype):
            yield IndexEntry(kind=IndexKind.NUMBER, field_key=BUCKET, value=1)

        with pytest.raises(ValueError, match=BUCKET):
            register_index_provider(other_provider, fields=[VirtualField(BUCKET, IndexKind.NUMBER)])
        assert other_provider not in providers_registry.providers()

    def test_registering_the_same_provider_twice_is_idempotent(self, registered):
        register_index_provider(sample_provider, fields=VIRTUAL_FIELDS)
        assert providers_registry.providers().count(sample_provider) == 1

    def test_clear_restores_the_builtin_and_drops_virtual_fields(self, registered):
        assert set(virtual_fields()) == {BUCKET, TAGS_UPPER}
        providers_registry.clear()
        assert providers_registry.providers() == (providers_registry.schema_provider,)
        assert virtual_fields() == {}

    def test_a_virtual_key_is_refused_as_a_declared_field_on_save(self, registered, field_def):
        with pytest.raises(FieldSchemaError, match="index provider") as exc:
            validate_fields([field_def(BUCKET, "number")], on_save=True)
        assert exc.value.key == BUCKET

    def test_the_same_definition_still_loads(self, registered, field_def):
        """A provider registered *after* a type was stored must not take that
        type offline: ``field_defs`` re-validates the stored definitions on
        every read, so refusing here would make every read — and the anonymous
        public endpoint — a 422 for a type that works."""
        assert validate_fields([field_def(BUCKET, "number")])[0].key == BUCKET

    def test_the_same_key_is_fine_once_the_provider_is_gone(self, registered, field_def):
        providers_registry.clear()
        assert validate_fields([field_def(BUCKET, "number")])[0].key == BUCKET


class TestFailureIsolation:
    async def test_a_raising_provider_is_logged_and_the_write_survives(
        self, db, make_type, make_record, field_def, registered, caplog
    ):
        register_index_provider(broken_provider)
        rtype = await make_type("product", [field_def("price", "number")])
        record = await make_record(rtype, {"price": "250", "tags": ["red"]})

        with caplog.at_level(logging.ERROR):
            await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

        assert [row.value for row in await rows(db, IndexNumber, BUCKET)] == [Decimal(2)]
        assert [row.value for row in await rows(db, IndexText, TAGS_UPPER)] == ["RED"]
        logged = [rec for rec in caplog.records if "index provider" in rec.getMessage()]
        assert len(logged) == 1
        assert "broken_provider" in logged[0].getMessage()
        assert record.uuid in logged[0].getMessage()
        assert logged[0].exc_info is not None
