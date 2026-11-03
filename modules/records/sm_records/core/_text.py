"""The one byte no string in this module may carry: ``\\x00``.

Postgres cannot store a NUL in ``text``, ``varchar`` or ``jsonb`` at all —
``invalid byte sequence for encoding "UTF8": 0x00`` comes from the *driver*,
as a ``DBAPIError`` raised while binding the parameter. That is not an error
any exception handler can usefully map: by the time it fires the statement has
failed, the transaction wants a rollback, and the caller gets a 500 for a
value the storage layer was never able to hold. One of the reproductions
needed no session at all (``?filter=name:eq:a%00b`` on the anonymous read
API), which is what made it worth a module of its own.

So the rule is applied on the way *in*, everywhere a string can reach the
database: the payload validator, the index coercers, the query-string grammar,
the claim checks, the importer's cells, and the type/field definitions. A
leaf module with no imports, because every one of those layers needs it and
none of them may depend on another.

Two spellings, because the callers want different things from a refusal: a
``bool`` for the coercers, whose contract is "this value has no place here"
rather than an exception, and a ``ValueError`` for the validators, which is
what pydantic turns into a field-level message.
"""

from __future__ import annotations

from typing import Any

__all__ = ["NUL", "NUL_PROBLEM", "check_no_nul", "has_nul"]

NUL = "\x00"

NUL_PROBLEM = "must not contain a NUL character (\\x00)"
"""One wording for every surface. The escape is spelled out because the
character itself is invisible in a message an editor reads, and "contains an
invalid character" is not something anybody can act on."""


def has_nul(value: Any) -> bool:
    """``True`` for a ``str`` carrying a NUL. Anything else is ``False`` —
    including ``bytes``, which never reach a text column on this path."""
    return isinstance(value, str) and NUL in value


def check_no_nul(value: Any) -> Any:
    """Pass ``value`` through, or raise :class:`ValueError` naming the rule.

    ``None``-tolerant like every other validator in ``schema/_scalars``: an
    optional field's base is a ``T | None`` union and the validators run on
    both arms.
    """
    if has_nul(value):
        raise ValueError(NUL_PROBLEM)
    return value
