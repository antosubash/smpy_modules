"""Records module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

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

TYPE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
"""A type key or field key: lowercase identifier, URL- and JSON-safe."""
MAX_KEY_LEN: Final = 64
MAX_LABEL_LEN: Final = 200
MAX_DISPLAY_TITLE_LEN: Final = 300
MAX_SLUG_LEN: Final = 200

TEXT_INDEX_LEN: Final = 512
"""Characters of a text value that land in the indexed column. 512 chars is
2048 bytes at four-byte UTF-8, under Postgres's 2704-byte btree ceiling —
redo that arithmetic before raising it. See the design doc §7.4."""

NUMBER_PRECISION: Final = 19
NUMBER_SCALE: Final = 5
"""``Numeric(19, 5)`` — five decimal places is the ``number`` type's contract,
validated on write so payload and index never disagree. Design doc §7.3."""

ORPHANED_KEY: Final = "_orphaned"
"""Reserved payload key holding values of deleted fields. Design doc §8.2."""

RESERVED_FIELD_KEYS: Final = frozenset({ORPHANED_KEY})
