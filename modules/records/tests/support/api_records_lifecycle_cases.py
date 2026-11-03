"""Shared setup for test_api_records_lifecycle."""

from __future__ import annotations

from tests.support.app_harness import (
    api_type,
)
from tests.support.app_harness import field as _field


async def _make_product_type(client, **type_cols):
    fields = [_field("name", "text", required=True), _field("price", "number")]
    return await api_type(client, "product", fields, **type_cols)
