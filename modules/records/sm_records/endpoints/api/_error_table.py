"""The documented refusals, as one table the schema and the docs both read.

``docs/api-reference.md``'s "Error table" is these rows, in this order, cell
for cell — and ``tests/test_openapi_errors.py`` fails if either moves without
the other. That is the point of keeping prose in a Python file: a generated
schema and a hand-maintained table are two descriptions of one contract, and
two descriptions drift. Before this existed, ``GET /openapi.json`` rendered
every records operation with only ``200``/``201``/``204`` and FastAPI's own
``422``, so a generated client saw none of the ``400``/``403``/``404``/``409``
/``413`` contract the table promises and had to discover it by being refused.

``when`` and ``body`` are the markdown cells verbatim, backticks and all,
because the comparison is character for character. Which *routes* can produce
which statuses is the other half and lives next door in
:mod:`sm_records.endpoints.api._responses`; the wire shapes live in
:mod:`sm_records.contracts.errors`.
"""

from __future__ import annotations

from typing import Final, NamedTuple

__all__ = ["ERROR_TABLE", "ErrorRow"]


class ErrorRow(NamedTuple):
    status: int
    when: str
    body: str


ERROR_TABLE: Final[tuple[ErrorRow, ...]] = (
    ErrorRow(
        400,
        "A filter or sort naming an unknown field",
        '`{"detail", "field", "reason": "unknown"}`',
    ),
    ErrorRow(
        400,
        "A filter or sort on a declared but unindexed field",
        '`{"detail", "field", "reason": "not_indexed"}`',
    ),
    ErrorRow(
        400,
        "An operator the field's kind does not support",
        '`{"detail", "field", "reason": "unsupported_op"}`',
    ),
    ErrorRow(
        400,
        "A filter value the field's kind cannot parse",
        '`{"detail", "field", "reason": "bad_value"}`',
    ),
    ErrorRow(
        400,
        "`?expand=` naming a non-relation field",
        '`{"detail", "field", "reason": "not_a_relation"}`',
    ),
    ErrorRow(
        400,
        "A malformed filter term, or `in` over `max_in_values`",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "More than `max_filter_terms` / `max_sort_terms` terms",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "`page` and `after` sent together",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "A cursor that does not decode, or replayed under a different sort",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "An import file that is not the format it claims, or a header naming an unknown column",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "A filter term containing a NUL (`\\x00`) character",
        '`{"detail"}`',
    ),
    ErrorRow(
        400,
        "*Public API only* — any of the above",
        '`{"detail"}` — no `field`, no `reason`',
    ),
    ErrorRow(
        401,
        "No session",
        '`{"detail": "Not authenticated"}` — the framework\'s, not this module\'s',
    ),
    ErrorRow(
        403,
        "Missing `records.view` / `records.edit` / `records.manage_types`",
        '`{"detail": "Permission required: records.edit"}`',
    ),
    ErrorRow(
        403,
        "The type's `allowed_roles` exclude the caller",
        '`{"detail"}` — names the type and the roles, deliberately',
    ),
    ErrorRow(
        403,
        "*Multi-tenant hosts* — the signed-in account has no tenant of its own",
        '`{"detail", "code": "tenant_required"}` — even when a tenant header was sent',
    ),
    ErrorRow(
        404,
        "Unknown type key, unknown uuid, a record in the trash on a non-trash read",
        '`{"detail"}`',
    ),
    ErrorRow(
        404,
        "*Public API* — any of: unknown type, non-public type, draft, trashed, unknown uuid",
        '`{"detail": "not found"}`',
    ),
    ErrorRow(
        404,
        "A preview job this process does not hold",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "`expected_version` no longer matches",
        '`{"detail", "current": RecordRead \\| TypeRead}`',
    ),
    ErrorRow(
        409,
        "A slug or `unique` value already claimed (possibly by a trashed record)",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "A delete blocked by `on_delete: restrict`",
        '`{"detail", "total": n, "referrers": [uuid, …], "hidden": n, "more": n}`',
    ),
    ErrorRow(
        409,
        "A restrictive schema change that would leave records invalid",
        '`{"detail", "report": DryRunReportRead}`',
    ),
    ErrorRow(
        409,
        "Re-adding a key that still holds orphaned values",
        '`{"detail", "conflicts": {key: n}}`',
    ),
    ErrorRow(
        409,
        "A filter or sort on a field mid-rebuild",
        '`{"detail", "field", "reason": "reindexing"}`',
    ),
    ErrorRow(
        409,
        "`DELETE /types/{key}` with a wrong `confirm_record_count`",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "A changed `collection` on `PUT /types/{key}`",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "A translation a type or a sibling will not allow",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "Turning `translatable` off while records exist in another language",
        '`{"detail"}`',
    ),
    ErrorRow(
        409,
        "A bulk action at least one named record refused",
        '`{"detail", "report": BulkReport}` — nothing was changed',
    ),
    ErrorRow(
        413,
        "An import body over `max_import_bytes`",
        '`{"detail"}`',
    ),
    ErrorRow(
        413,
        "An import file holding more rows than `max_import_rows`",
        '`{"detail"}` — refused before anything is written',
    ),
    ErrorRow(
        413,
        "A bulk action naming more than `max_bulk_records` records",
        '`{"detail"}` — refused before a record is touched',
    ),
    ErrorRow(
        413,
        "Any other `/api/records/*` write body over `max_payload_bytes` + 65,536",
        '`{"detail"}` — refused from `Content-Length`, before the body is read',
    ),
    ErrorRow(
        422,
        "A payload that does not satisfy the schema",
        '`{"detail", "errors": [{"field", "message"}, …]}`',
    ),
    ErrorRow(
        422,
        "An invalid field or type definition",
        '`{"detail", "errors"}`',
    ),
    ErrorRow(
        422,
        "`rescan: true` with `fields` that are not the type's stored ones",
        '`{"detail", "errors"}` — nothing was scanned or marked',
    ),
    ErrorRow(
        422,
        "A NUL (`\\x00`) in a payload value, a `unique` value, a type label or a field definition",
        '`{"detail", "errors"}`',
    ),
    ErrorRow(
        422,
        "`locale` on `PUT /records/{uuid}`",
        "FastAPI validation error",
    ),
    ErrorRow(
        422,
        "`match_by` naming a non-unique field; an unknown `format`; an undeclared `collection`",
        '`{"detail", "errors"}`',
    ),
    ErrorRow(
        422,
        "`on_error=abort` and a bad row",
        '`{"detail", "report": ImportReport}`',
    ),
    ErrorRow(
        422,
        "`page` outside `1 … 1000000`, `page_size` below 1",
        "FastAPI validation error",
    ),
    ErrorRow(
        422,
        "An empty `uuids` list, or an `action` that is not one of the five",
        "FastAPI validation error",
    ),
    ErrorRow(
        500,
        "Anything unanticipated on `/api/records/*`",
        '`{"detail": "internal error"}` — always JSON',
    ),
)
