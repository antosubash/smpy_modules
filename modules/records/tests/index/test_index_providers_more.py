"""test_index_providers cases."""

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
from sm_records.records.index import providers as providers_registry
from sm_records.records.index.query import Filter, FilterOp, QueryError, Sort, build_query
from sm_records.records.index.reindex import reindex_type
from sm_records.records.index.writer import delete_index, write_index
from sm_records.models import INDEX_TABLES, IndexNumber, IndexText, tables_for
from sm_records.schema.fields import FieldSchemaError, validate_fields
from sqlalchemy import delete, select
from tests.support.index_providers_cases import sample_provider, broken_provider, registered, catalogue, rows, found, snapshot, TestWritePath, TestQuerying, TestRegistry, TestFailureIsolation, BUCKET, TAGS_UPPER, VIRTUAL_FIELDS
