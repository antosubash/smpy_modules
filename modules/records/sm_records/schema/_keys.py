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

from sm_records.constants import MAX_KEY_LEN, TYPE_KEY_PATTERN
from sm_records.index._fixed import RESERVED_FIELD_KEYS
from sm_records.index._registry import reduce_keys
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


def validate_key(raw: dict[str, Any], seen: set[str], *, on_save: bool = False) -> str:
    """Validate one field key. ``on_save`` is what separates the two callers.

    Every rule below is a property of the definition itself and holds forever
    — except the virtual-key refusal, which is a property of *what the host
    happens to have registered right now*. A provider registered after a type
    was stored would otherwise retroactively invalidate that type, and since
    ``services._payload.field_defs`` re-validates the stored definitions on
    every read, the type would answer 422 to every caller including the
    anonymous public endpoint. So that one check runs only when a schema is
    being *saved* (``services._schema.normalise``, the one path a type
    create, update or rollback goes through); a stored definition that
    collides is loaded as it stands and the declared field wins the filter
    grammar, with one warning per type (``index.query._resolve``).
    """
    raw_key = raw.get("key")
    require(isinstance(raw_key, str) and raw_key, None, "every field needs a 'key'")
    key = str(raw_key)
    # Reserved first: `_orphaned` also fails the pattern, and "reserved by the
    # module" tells the author why far better than a regex does. The rest is
    # every ``Record`` column plus the fixed filter/sort columns
    # (``index._fixed.RESERVED_FIELD_KEYS``), which the query layer resolves
    # ahead of the type's own fields — so such a field indexed correctly and
    # was then filtered and sorted from the wrong data, with a 200.
    reserved = "key is reserved: it names a column every record already has, "
    require(key not in RESERVED_FIELD_KEYS, key, reserved + "so a filter would shadow it")
    # Registered at runtime by a host's index provider (design §7.6), so this
    # one cannot join ``RESERVED_FIELD_KEYS`` — that set is static per process
    # and mirrored by hand in the TypeScript editor, which has no way to know
    # what the host installed. The editor therefore cannot grey the key out;
    # refusing it on save with a message that names the reason is the
    # contract, and the README says so. ``on_save`` is why it is the only
    # check here that a *load* skips — see the docstring.
    if on_save:
        require(
            key not in virtual_fields(),
            key,
            "key is reserved by an index provider: it is a virtual field, queryable on every "
            "type's records, so a declared field of the same key would shadow it",
        )
        # The same rule for the other kind of provider key (Phase 5 §5.2). A
        # reduce key is not read by the filter grammar, so it shadows nothing
        # there — but ``?reduce=`` and ``?group_by=`` share one namespace with
        # declared fields on the aggregate endpoint, and one key answering two
        # different questions depending on which parameter named it is the
        # ambiguity the single-owner rule exists to prevent.
        require(
            key not in reduce_keys(),
            key,
            "key is reserved by a reduce provider: it names a maintained aggregate, which "
            "the aggregate endpoint resolves alongside this type's fields",
        )
    require(KEY_RE.match(key), key, f"key must match {TYPE_KEY_PATTERN}")
    require(len(key) <= MAX_KEY_LEN, key, f"key must be at most {MAX_KEY_LEN} characters")
    require(key not in seen, key, "duplicate field key")
    return key
