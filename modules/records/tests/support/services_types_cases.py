"""Shared setup for test_services_types."""

from __future__ import annotations
import pytest
from sm_records.models import Record, RecordType, RecordTypeRevision
from sm_records.records.services import records as record_service
from sm_records.records.services import types as service
from sm_records.records.services.errors import (
    Conflict,
    NotFound,
    ReferencedByOthers,
    ValidationFailed,
)
from sm_records.core.settings import RecordsSettings
from sqlalchemy import select

@pytest.fixture
def product_fields(field_def):
    return [field_def("title", "text"), field_def("price", "number", indexed=False)]


async def revisions(db, rtype):
    stmt = (
        select(RecordTypeRevision)
        .where(RecordTypeRevision.type_id == rtype.id)
        .order_by(RecordTypeRevision.id)
    )
    return list((await db.execute(stmt)).scalars().all())
