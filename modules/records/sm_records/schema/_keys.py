"""Field keys: what one may not be called, and the error that says so.

Split from :mod:`sm_records.schema.fields` along the seam the reservation
rules created. Two of them are unlike every other check in that package —
they consult state outside the definition being validated: the derived
``RESERVED_FIELD_KEYS`` (every column a record already has) and the
*runtime* registry of virtual fields an index provider projects. Keeping
them together with the message that explains each is what stops the two
being confused for one rule.

:class:`FieldSchemaError` and :func:`require` live here rather than in
``fields`` because this module is the first thing that raises them and the
import would otherwise be a cycle.
"""

from __future__ import annotations

import re
from typing import Any

from sm_records.constants import MAX_KEY_LEN, RESERVED_FIELD_KEYS, TYPE_KEY_PATTERN
from sm_records.index.providers import virtual_fields

KEY_RE = re.compile(TYPE_KEY_PATTERN)
"""A key: lowercase identifier. Shared with ``fields``, which matches a
``relation``'s ``target_type`` against the same shape."""


class FieldSchemaError(ValueError):
    """A field definition that cannot mean anything. The message always names
    the field key, because a type editor saves the whole list at once and
    "invalid field" without a key is unactionable."""

    def __init__(self, key: str | None, problem: str) -> None:
        self.key = key
        self.problem = problem
        where = f"field {key!r}" if key else "fields"
        super().__init__(f"{where}: {problem}")


def require(condition: Any, key: str | None, problem: str) -> None:
    if not condition:
        raise FieldSchemaError(key, problem)


def validate_key(raw: dict[str, Any], seen: set[str]) -> str:
    raw_key = raw.get("key")
    require(isinstance(raw_key, str) and raw_key, None, "every field needs a 'key'")
    key = str(raw_key)
    # Reserved first: `_orphaned` also fails the pattern, and "reserved by the
    # module" tells the author why far better than a regex does. The rest is
    # every ``Record`` column plus the fixed filter/sort columns
    # (``constants._reserved_field_keys``), which the query layer resolves
    # ahead of the type's own fields — so such a field indexed correctly and
    # was then filtered and sorted from the wrong data, with a 200.
    reserved = "key is reserved: it names a column every record already has, "
    require(key not in RESERVED_FIELD_KEYS, key, reserved + "so a filter would shadow it")
    # Registered at runtime by a host's index provider (design §7.6), so this
    # one cannot join ``RESERVED_FIELD_KEYS`` — that set is static per process
    # and mirrored by hand in the TypeScript editor, which has no way to know
    # what the host installed. The editor therefore cannot grey the key out;
    # refusing it here with a message that names the owner is the contract,
    # and the README says so.
    require(
        key not in virtual_fields(),
        key,
        "key is reserved by an index provider: it is a virtual field, queryable on every "
        "type's records, so a declared field of the same key would shadow it",
    )
    require(KEY_RE.match(key), key, f"key must match {TYPE_KEY_PATTERN}")
    require(len(key) <= MAX_KEY_LEN, key, f"key must be at most {MAX_KEY_LEN} characters")
    require(key not in seen, key, "duplicate field key")
    return key
