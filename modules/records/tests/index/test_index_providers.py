"""Index providers as a real extension point (design doc §7.6).

A host module projects rows this module knows nothing about, and those rows
are queryable — which is the half that did not exist before Phase 4: a
provider could always *write* under a key no type declares, and the filter
grammar, which resolves a key through the type's ``fields``, could never read
it back.

The sample provider below is the one the README documents: a NUMBER bucket
computed from ``price`` and a TEXT projection of ``tags``, uppercased and
multi-valued. The HTTP half — filters, sorts and the 422 — lives in
``test_index_providers_api.py`` for the 300-line cap.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from sm_records.records.index import (
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
