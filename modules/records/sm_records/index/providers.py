"""Index providers — how a document becomes index rows, and the seam that lets
another module add rows this module knows nothing about.

YesSql's ``IndexProvider`` is the only place that knows the projection, which
is what makes indexing extensible without touching storage. The Python
equivalent is a callable and a process-global registry (design doc §7.6). The
built-in provider projects every field marked ``indexed: true``; a module
wanting a computed bucket, a normalised sort key or a denormalised value from
a related record registers its own and the writer picks it up.

**Coercion never raises.** A value that cannot become the type its column
holds is simply absent from the index for that field (design doc §8.4) — that
is what makes a ``text`` → ``number`` change safe to reindex without
rewriting a single payload, and it is why the dry-run reports how many rows
would drop out before anything runs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sm_records.constants import ORPHANED_KEY
from sm_records.index._coerce import (
    coerce_bool,
    coerce_date,
    coerce_datetime,
    coerce_number,
    coerce_ref,
    coerce_text,
)
from sm_records.index._fields import read_field, relation_target
from sm_records.models import Record, RecordType
from sm_records.schema.types import IndexKind


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One row-to-be, before it knows which table it lands in.

    ``value`` is already coerced to the column's type. For ``REF`` it is the
    pair ``(target_uuid, target_type_id)``, because that table's identity is
    two columns rather than one.
    """

    kind: IndexKind
    field_key: str
    value: Any


IndexProvider = Callable[[Record, RecordType], Iterable[IndexEntry]]

TypeResolver = Callable[[str], int | None]
"""Type key → ``records_type.id``. A ``relation`` is stored by type *key* and
indexed by type *id*, and resolving one to the other needs the session."""


def _unresolvable(_key: str) -> int | None:
    return None


_resolver: ContextVar[TypeResolver] = ContextVar("records_type_resolver", default=_unresolvable)


@contextmanager
def use_type_resolver(resolve: TypeResolver) -> Iterator[None]:
    """Bind the type-key resolver for the duration of one index write.

    A provider is a plain ``(record, rtype)`` callable registered once at
    import time, so it cannot take a session-bound resolver as an argument.
    Passing it in a context variable keeps the registry's signature free of
    the request while still letting the built-in provider — and any third
    party's — resolve a relation target. ``writer.write_index`` is the only
    caller that has to remember this.
    """
    token = _resolver.set(resolve)
    try:
        yield
    finally:
        _resolver.reset(token)


def current_type_resolver() -> TypeResolver:
    """The resolver bound by ``use_type_resolver``, or one that resolves
    nothing — outside a write, a relation simply does not index."""
    return _resolver.get()


def _entry(kind: IndexKind, key: str, value: object) -> IndexEntry | None:
    if kind is IndexKind.TEXT:
        coerced: object | None = coerce_text(value)
    elif kind is IndexKind.NUMBER:
        coerced = coerce_number(value)
    elif kind is IndexKind.BOOL:
        coerced = coerce_bool(value)
    elif kind is IndexKind.DATE:
        coerced = coerce_date(value)
    else:
        coerced = coerce_datetime(value)
    return None if coerced is None else IndexEntry(kind=kind, field_key=key, value=coerced)


def _ref_entry(key: str, value: object, declared_target: str | None, resolve: TypeResolver):
    """A relation indexes to ``(uuid, type_id)``; an unknown target type is
    skipped rather than raised, exactly as a failed coercion is — a type
    deleted out from under a stale payload must not stop the reindex.

    The row is keyed on the *declared* target — the field's ``target_type`` —
    and only falls back to the key the payload carries when the definition
    names none. Trusting the payload's key made a made-up ``type`` index
    nowhere (or, worse, against another type), which is a reference that
    exists in the document and not in ``records_index_ref``: ``restrict``
    would then find no referrer and let the target be deleted. The payload's
    key cannot disagree with the declared one on any write
    (``services._relations.check_targets``), so this only ever picks the same
    value — for rows written before that check existed, it picks the right one.
    """
    parsed = coerce_ref(value)
    if parsed is None:
        return None
    claimed, uuid = parsed if isinstance(parsed, tuple) else (None, parsed)
    target_key = declared_target or claimed
    if not target_key:
        return None
    type_id = resolve(target_key)
    if type_id is None:
        return None
    return IndexEntry(kind=IndexKind.REF, field_key=key, value=(uuid, type_id))


def make_schema_provider(resolve_type_id: TypeResolver) -> IndexProvider:
    """The built-in provider, bound to a way of resolving relation targets."""

    def schema_provider(record: Record, rtype: RecordType) -> Iterator[IndexEntry]:
        data = record.data or {}
        # The same fallback the read path takes (``schema.compile.from_stored``):
        # a declared key that lives only under ``_orphaned`` is a value restored
        # with a re-added field (§8.8), and the payload catches up lazily on the
        # record's next write. Indexing from the top level only would leave that
        # field queryable for nobody until every record happened to be edited.
        orphaned = data.get(ORPHANED_KEY)
        if not isinstance(orphaned, dict):
            orphaned = {}
        for raw in rtype.fields or []:
            field = read_field(raw)
            if field is None:
                continue
            if field.key in data:
                value = data[field.key]
            elif field.key in orphaned:
                value = orphaned[field.key]
            else:
                continue
            if value is None:
                continue
            # A to-many field given a scalar still indexes: the payload may
            # predate the field becoming ``many``, and one row is the honest
            # projection of one value.
            values = value if field.many and isinstance(value, list) else [value]
            for item in values:
                entry = (
                    _ref_entry(field.key, item, relation_target(raw), resolve_type_id)
                    if field.kind is IndexKind.REF
                    else _entry(field.kind, field.key, item)
                )
                if entry is not None:
                    yield entry

    return schema_provider


schema_provider: IndexProvider = make_schema_provider(lambda key: current_type_resolver()(key))
"""The default-registered instance. It defers to whatever resolver the current
write bound, so one module-level provider serves every session."""


@dataclass(frozen=True, slots=True)
class VirtualField:
    """A key a provider projects that no Record Type declares (design §7.6).

    Declaring it is what makes the key *queryable*: the filter grammar resolves
    a field key to an index table through the type's ``fields``, and a
    provider-only key would otherwise be written and never readable. ``many``
    says one record may hold several rows for the key (a multiselect-style
    projection), which decides ``eq``'s any-of reading and ``ne``'s none-of.

    The key is global — every type's records may carry it — so it is refused
    as a declared field key on any type (``schema.fields.validate_fields``),
    exactly as the document-table columns are.

    **A virtual field is never refused as ``reindexing``.** The 409 of design
    §8.5 belongs to a key sitting in a type's ``reindex_pending``, and a
    provider has no entry there: changing what it projects is the host
    redeploying, not a schema edit this module can see. The rows go stale
    silently until someone runs ``python -m sm_records.cli reindex``, which is
    the trade for an extension point the schema knows nothing about.
    """

    key: str
    kind: IndexKind
    many: bool = False


_providers: list[IndexProvider] = [schema_provider]
_virtual: dict[str, VirtualField] = {}
_owners: dict[str, IndexProvider] = {}
_shadowed: set[tuple[str, str]] = set()


def _name(provider: IndexProvider) -> str:
    return getattr(provider, "__qualname__", None) or repr(provider)


def register(provider: IndexProvider, *, fields: Iterable[VirtualField] = ()) -> None:
    """Add a provider and the virtual fields it projects.

    Idempotent on the callable — registering the same one twice would
    otherwise double every row it yields. A virtual key already registered by
    a *different* provider is a ``ValueError``: two projections under one key
    would answer a filter with the union of both, silently. The ownership is
    what is checked, not the declaration: two providers agreeing on kind and
    ``many`` still write two sets of rows under one key.

    Every key is checked before any is recorded, so a rejected call leaves the
    registry exactly as it found it rather than half-registered.

    Call it at import time or from a module's ``on_startup``; the built-in
    ``schema_provider`` is always first and cannot be removed.
    """
    claimed = list(fields)
    for field in claimed:
        owner = _owners.get(field.key)
        if owner is not None and owner is not provider:
            raise ValueError(f"virtual field {field.key!r} is already registered by {_name(owner)}")
    for field in claimed:
        _virtual[field.key] = field
        _owners[field.key] = provider
    if provider not in _providers:
        _providers.append(provider)


def providers() -> tuple[IndexProvider, ...]:
    return tuple(_providers)


def virtual_fields() -> dict[str, VirtualField]:
    """Every provider-projected key, by key. Read by the filter grammar and by
    ``validate_fields`` — one registry, so the two cannot disagree."""
    return dict(_virtual)


def clear() -> None:
    """Drop every registered provider *except* the built-in, restoring the
    state a fresh import gives.

    Emptying the list outright is what a test usually means, but a test that
    did so and forgot to restore would leave every later record in the process
    with an empty index — a wrong-answer failure a long way from its cause.
    Virtual fields go with their providers.
    """
    _virtual.clear()
    _owners.clear()
    _shadowed.clear()
    _providers[:] = [schema_provider]


def note_shadowed(type_key: str, field_key: str) -> bool:
    """Record that ``type_key`` declares a field shadowing a virtual key, and
    say whether this is the first time — so the query layer logs the collision
    once per type rather than once per request.

    Kept next to the registry because the registry is what creates the
    collision and :func:`clear` is what ends it: a test that clears the
    providers gets a clean slate here too, instead of a memo from an earlier
    test silently swallowing the warning it asserts.
    """
    seen = (type_key, field_key)
    if seen in _shadowed:
        return False
    _shadowed.add(seen)
    return True
