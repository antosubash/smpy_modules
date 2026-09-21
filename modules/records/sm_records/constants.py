"""Records module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - see ``__getattr__`` at the bottom
    RESERVED_FIELD_KEYS: Final[frozenset[str]]

PACKAGE: Final = "sm_records"
"""The import package, and the attribute on ``app.state`` the services
container lives under. Prefixed because ``records`` is an existing PyPI
package — the same reason the AI module imports as ``sm_ai``."""

MODULE_NAME: Final = "Records"
"""``ModuleMeta.name``, and the Inertia page-name prefix."""

DISTRIBUTION: Final = "simple_module_records"

ROUTE_PREFIX_API: Final = "/api/records"
VIEW_PREFIX: Final = "/admin/records"
# Trailing slash: the list route is registered at "/" under VIEW_PREFIX, so
# linking to the bare prefix costs a 307 round trip on every navigation.
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_GROUP: Final = "Content"
MENU_ICON: Final = "database"
MENU_ORDER: Final = 300

MENU_GROUP_TYPES: Final = "Records"
"""Sidebar group for a per-type entry (:func:`sm_records.menu.type_menu_items`).

Deliberately its own group and not :data:`MENU_GROUP`: a type called "Pages"
sitting as a peer of pagebuilder's "Pages" or news' "Articles" under the
shared "Content" heading gives no sign it is a record type rather than
another module's screen. The hub entry stays in :data:`MENU_GROUP` — it is
how every *other* type is reached, not itself a type."""

MENU_ORDER_TYPE: Final = MENU_ORDER + 1
"""Order of a per-type sidebar entry — one past the hub, so every type a host
opts in sits directly under "Records". The registry sorts by ``order`` alone
and stably, which is what makes :mod:`sm_records.menu`'s alphabetical
insertion the tiebreak between them.

It also decides where the "Records" group itself renders: a group's position
is set by the lowest ``order`` among its items (see ``MenuRegistry`` in
``simple_module_core.menu``), and nothing else currently sits between the hub's
``MENU_ORDER`` and this value, so keeping it one past the hub is what puts the
"Records" group directly after "Content" in the admin sidebar."""

MENU_SKIP_PREFIXES: Final = ("/api/", "/static", "/health")
"""Request paths :class:`sm_records._menu_middleware.MenuSyncMiddleware` never
re-reads the menu for: none of them renders a sidebar, and the JSON API is the
one surface where a per-request read would show up in a statement count."""

MODULE_ATTR: Final = "records_module"
"""``app.state`` attribute holding the :class:`~sm_records.module.RecordsModule`
instance. Parked there by ``register_middleware`` so a request handler can reach
the module's own runtime state — today only to mark the sidebar stale after a
type write (:func:`sm_records.menu.mark_dirty`)."""

#: The framework's settings module, by ``ModuleMeta.name``. Depending on it
#: guarantees ``app.state.settings.module_registry`` exists by the time
#: ``register_settings`` runs — the host topo-sorts modules on this field.
_MODULE_SETTINGS: Final = "Settings"

PERM_GROUP: Final = "records"
PERM_VIEW: Final = "records.view"
PERM_EDIT: Final = "records.edit"
PERM_MANAGE_TYPES: Final = "records.manage_types"

_PAGE_TYPES: Final = f"{MODULE_NAME}/Types"
_PAGE_RECORD_LIST: Final = f"{MODULE_NAME}/RecordList"
_PAGE_RECORD_EDITOR: Final = f"{MODULE_NAME}/RecordEditor"
_PAGE_TYPE_EDITOR: Final = f"{MODULE_NAME}/TypeEditor"

TYPE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
"""A type key or field key: lowercase identifier, URL- and JSON-safe."""
MAX_KEY_LEN: Final = 64
MAX_LABEL_LEN: Final = 200

MAX_COLLECTION_NAME_LEN: Final = 32
"""A collection's name, which obeys ``TYPE_KEY_PATTERN`` too (Phase 5 §6.1).

Shorter than a key because the name is a table-name *prefix*: Postgres
truncates an identifier at 63 bytes, and the longest thing built on it —
``ix_records_c_<name>_index_datetime_lookup`` — has to fit under that."""

RESERVED_COLLECTION_NAMES: Final = frozenset(
    {"default", "global", "records", "type", "index", "reduce"}
)
"""Names a collection may not take.

``default`` and ``global`` because they are what a reader would expect to mean
"the shared tables", which is exactly the thing that has no name. The rest
because ``records_c_type_record`` reads as a table about types rather than a
collection called ``type`` — the ``c_`` infix already prevents the collision,
and this prevents the confusion."""
MAX_DISPLAY_TITLE_LEN: Final = 300
MAX_SLUG_LEN: Final = 200

TEXT_INDEX_LEN: Final = 512
"""Characters of a text value that land in the indexed column. 512 chars is
2048 bytes at four-byte UTF-8, under Postgres's 2704-byte btree ceiling —
redo that arithmetic before raising it. See the design doc §7.4."""

REDUCE_GROUP_LEN: Final = 512
"""Characters of a reduce group value that land in ``records_index_reduce``.

The same ceiling as :data:`TEXT_INDEX_LEN` and for the same reason — the
column is part of a unique index, so it is bound by Postgres's btree limit —
and deliberately the same number, so a reduce spec grouping on a text field
buckets exactly as a filter on that field matches (Phase 5 §5.2)."""

NUMBER_PRECISION: Final = 19
NUMBER_SCALE: Final = 5
"""``Numeric(19, 5)`` — five decimal places is the ``number`` type's contract,
validated on write so payload and index never disagree. Design doc §7.3."""

ORPHANED_KEY: Final = "_orphaned"
"""Reserved payload key holding values of deleted fields. Design doc §8.2."""


def _reserved_field_keys() -> frozenset[str]:
    """Field keys a Record Type may never declare — see ``RESERVED_FIELD_KEYS``.

    Derived, never hand-typed: every column of the ``Record`` row plus
    ``FIXED_COLUMNS`` (the filterable/sortable projection of §7.2) plus
    ``_orphaned``. ``index.query._term`` resolves a fixed column *before* the
    type's own fields, so a field keyed ``status`` or ``position`` was legal,
    indexable, and then answered from ``records_record`` — a 200 with the
    wrong rows. Refusing the key at schema-save time is the fix; deriving the
    set from the model is what stops it drifting the next time a column is
    added to ``Record``.
    """
    from sm_records.index.query import FIXED_COLUMNS
    from sm_records.models import Record

    columns = {str(column.key) for column in Record.__table__.columns}
    return frozenset({ORPHANED_KEY, *FIXED_COLUMNS, *columns})


REINDEX_ALL: Final = "*"
"""The ``reindex_pending`` entry meaning "rebuild the whole type", enqueued by
a ``display_field`` change — every record's ``display_title`` is denormalised
from it (design doc §18 Q2). Safe as a sentinel because ``TYPE_KEY_PATTERN``
requires a lowercase letter first, so no field key can be ``*`` and a
whole-type rebuild therefore never refuses a filter."""

EXPAND_PARAM: Final = "expand"
"""Query parameter naming the relation fields to resolve on a read (design
§9): comma-separated field keys, depth one, refused with a 400 for a key that
is not a ``relation`` field of the type. Admin API only — the public read API
never expands (§10)."""

PUBLIC_ROUTE_METHODS: Final = frozenset({"GET", "HEAD"})
"""The only verbs the anonymous read API answers, and the only ones its
``PublicRouteRegistry`` exemption covers — pinned so a future route under the
same prefix cannot widen the exemption by accident (§10)."""

MAX_LOCALE_LEN: Final = 16
"""``records_record.locale`` width — a BCP 47 tag such as ``pt-BR``."""

LOCALE_PATTERN: Final = r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$"
"""A content locale, lowercased. Deliberately narrower than BCP 47's full
grammar, for the reason :mod:`pagebuilder.locales` gives about its own: the tag
is a column value and a query-string value, so accepting two spellings of one
language would let ``?locale=DE`` and ``?locale=de`` address different sets.
Matching is done case-insensitively by :func:`sm_records.locales.resolve`; the
*configured* list is required to be in this form."""

DEFAULT_CONTENT_LOCALE: Final = "en"
"""The locale a record is in when nobody says otherwise, and the value the
migration backfills onto every row written before this module had a language.
Also :attr:`~sm_records.settings.RecordsSettings.default_content_locale`'s
default, and the ``server_default`` of ``records_record.locale``."""

TRANSLATION_GROUP_LEN: Final = 32
"""``records_record.translation_group`` width: the first record's uuid hex."""

TRANSLATIONS_PARAM: Final = "translations"
"""``?translations=true`` on a record read lists the siblings (one extra
query); never honoured on the list endpoint, where it would be one per row."""

LOCALE_PARAM: Final = "locale"
"""``?locale=`` on the public list. Absent means the default content locale,
never "all": an anonymous reader asks for one site (Phase 5 §4.4)."""

RESERVED_TYPE_KEYS: Final = frozenset({"types", "new"})
"""Type keys that would shadow a view route: ``/admin/records/types/...`` is
the schema editor and ``/admin/records/{key}/new`` the record editor, and a
type keyed ``types`` would put its record list at the editor's address."""


def __getattr__(name: str) -> Any:
    """Resolve ``RESERVED_FIELD_KEYS`` on first use (PEP 562).

    It is derived from ``Record.__table__`` and ``index.query.FIXED_COLUMNS``,
    and both of those modules import *this* one — so the set cannot be built
    while this module is still executing. Computing it on the first attribute
    read breaks the cycle and then caches into ``globals()``, so every later
    lookup is an ordinary module attribute. ``TYPE_CHECKING`` at the top of
    the file declares the name for type checkers, which do not run this.
    """
    if name == "RESERVED_FIELD_KEYS":
        value = _reserved_field_keys()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
