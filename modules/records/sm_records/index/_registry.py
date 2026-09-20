"""The virtual-field registry: which keys a provider claims, and the rules.

Split from :mod:`sm_records.index.providers` along the seam design §7.6 draws
twice. That module is a *projection* — what a document becomes, and the
built-in implementation of it. This one is the **registry of keys**: which
provider owns which virtual field, whether a key is usable at all, and the
two once-per-process memos the writer and the query builder log through.

Keeping them apart is what stops the key rules drifting from the field rules:
everything here answers the same question ``schema._keys`` answers for a
*declared* key, against the same derived reserved set.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sm_records import constants
from sm_records.index._fixed import FIXED_COLUMNS
from sm_records.schema.types import IndexKind

_Provider = Callable[..., Any]
"""``providers.IndexProvider``, spelled loosely on purpose: this module stores
providers as opaque identities and never calls one, and importing the precise
alias would make the two modules import each other."""

_KEY_RE = re.compile(constants.TYPE_KEY_PATTERN)


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


_virtual: dict[str, VirtualField] = {}
_owners: dict[str, _Provider] = {}
_reduce: dict[str, _Provider] = {}
"""Reduce-spec keys, by key, to the spec that owns each (Phase 5 §5.2).

Here rather than beside the specs themselves because this module is the
registry of *names*: a reduce key is a virtual key in every respect that
matters to a schema author — reserved on save, refused as a declared field,
one owner — and keeping the two sets apart in two files is how one of them
ends up claimable twice."""
_shadowed: set[tuple[str, str]] = set()
_dropped: set[tuple[str, str]] = set()


def _name(provider: _Provider) -> str:
    return getattr(provider, "__qualname__", None) or repr(provider)


def _check_key(key: str, *, virtual: bool = True) -> None:
    """A virtual key must be a key, and must not be one nothing can read.

    The same rules a *declared* field key obeys (``schema._keys.validate_key``),
    for the same reasons and with one registry behind both: the filter grammar
    resolves a fixed column (``status``, ``position``, …) before it ever looks
    at the virtual registry, so a provider claiming one wrote rows on every
    save that no query could ever reach — dead weight discovered only by the
    host's own confusion. A key that does not match ``TYPE_KEY_PATTERN`` is
    unreachable for a blunter reason: ``deps.parse_filters`` splits on ``:``
    and the editor mirrors the pattern.

    ``ValueError`` rather than a log line because ``register`` is called from
    a host's own code at import or ``on_startup`` — there is a person reading
    a traceback, and the alternative is rows nobody can query.
    """
    kind = "virtual field" if virtual else "reduce spec"
    taken = _reduce if virtual else _virtual
    if key in taken:
        raise ValueError(
            f"{kind} {key!r} is already registered as a "
            f"{'reduce spec' if virtual else 'virtual field'}: one key, one owner, whichever "
            "kind of provider claimed it first"
        )
    reserved = frozenset(constants.RESERVED_FIELD_KEYS) | FIXED_COLUMNS
    if key in reserved:
        raise ValueError(
            f"{kind} {key!r} is a reserved key: it names a column every record "
            "already has, which the query grammar resolves first — the rows would be "
            "written and never readable"
        )
    if not _KEY_RE.match(key):
        raise ValueError(
            f"{kind} {key!r} must match {constants.TYPE_KEY_PATTERN}, like any other field key"
        )
    if len(key) > constants.MAX_KEY_LEN:
        raise ValueError(f"{kind} {key!r} must be at most {constants.MAX_KEY_LEN} characters")


def claim(provider: _Provider, fields: Iterable[VirtualField]) -> None:
    """Record ``provider`` as the owner of every key in ``fields``.

    Every key is checked before any is recorded, so a rejected call leaves the
    registry exactly as it found it rather than half-registered. See
    :func:`sm_records.index.providers.register`, the one caller.
    """
    claimed = list(fields)
    for field in claimed:
        _check_key(field.key)
        owner = _owners.get(field.key)
        if owner is not None and owner is not provider:
            raise ValueError(f"virtual field {field.key!r} is already registered by {_name(owner)}")
    for field in claimed:
        _virtual[field.key] = field
        _owners[field.key] = provider


def claim_reduce(key: str, spec: _Provider) -> None:
    """Record ``spec`` as the owner of a reduce key — see
    :func:`sm_records.index.reduce.register_reduce_provider`, the one caller.

    The same rules a virtual key obeys, checked by the same function: a reduce
    key is queried through the aggregate endpoint rather than the filter
    grammar, but it is just as global (every type may carry it) and just as
    unreadable if it collides, so it is refused as a declared field key in the
    same place and with the same kind of message.
    """
    _check_key(key, virtual=False)
    owner = _reduce.get(key)
    if owner is not None and owner is not spec:
        raise ValueError(f"reduce spec {key!r} is already registered by {_name(owner)}")
    _reduce[key] = spec


def reduce_keys() -> frozenset[str]:
    """Every registered reduce key. Read by ``schema._keys.validate_key``, so
    a declared field cannot shadow one, and by the aggregate endpoint, so an
    unknown ``?reduce=`` is a 400 naming it rather than an empty result."""
    return frozenset(_reduce)


def clear_reduce() -> None:
    """Drop every claimed reduce key — the registry half of
    :func:`sm_records.index.reduce.clear_reduce_providers`."""
    _reduce.clear()


def virtual_fields() -> dict[str, VirtualField]:
    """Every provider-projected key, by key. Read by the filter grammar and by
    ``validate_fields`` — one registry, so the two cannot disagree."""
    return dict(_virtual)


def clear_virtual() -> None:
    """Drop every claimed key and both memos — the registry half of
    :func:`sm_records.index.providers.clear`."""
    _virtual.clear()
    _owners.clear()
    _shadowed.clear()
    _dropped.clear()


def note_dropped(provider_name: str, field_key: str) -> bool:
    """Record that a provider's entry under ``field_key`` was dropped by the
    writer, and say whether this is the first time — so a projection that
    disagrees with its own declaration is one log line rather than one per
    record saved. Cleared with the registry, exactly as :func:`note_shadowed`
    is and for the same reason."""
    seen = (provider_name, field_key)
    if seen in _dropped:
        return False
    _dropped.add(seen)
    return True


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
