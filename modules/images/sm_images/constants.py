"""Images module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal - see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "sm_images"
"""The import package, and the attribute on ``app.state`` the services
container lives under. Prefixed because ``images`` is a generic name on PyPI -
the same reason records imports as ``sm_records``."""

MODULE_NAME: Final = "Images"
"""``ModuleMeta.name``, and the Inertia page-name prefix."""

DISTRIBUTION: Final = "simple_module_images"

LOCALE_NAMESPACE: Final = "images"
"""The namespace ``locale_dirs`` registers the catalogue under, and the prefix
of every key in ``locales/*.json``."""

TABLE_PREFIX: Final = "images_"
BASE_NAME: Final = "images"
"""The argument of ``create_module_base``."""

ROUTE_PREFIX_API: Final = "/api/images"
VIEW_PREFIX: Final = "/admin/images"
PUBLIC_PREFIX: Final = "/images"

# Trailing slash: the list route is registered at "/" under VIEW_PREFIX, so
# linking to the bare prefix costs a 307 round trip on every navigation.
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_ICON: Final = "image"
MENU_ORDER: Final = 350
MENU_LABEL: Final = "Image collections"
MENU_LABEL_KEY: Final = "images.menu.collections"
MENU_GROUP: Final = "Images"
MENU_GROUP_KEY: Final = "images.menu.group_images"

#: The framework's settings module, by ``ModuleMeta.name``. Depending on it
#: guarantees ``app.state.settings.module_registry`` exists by the time
#: ``register_settings`` runs - the host topo-sorts modules on this field.
_MODULE_SETTINGS: Final = "Settings"

NOT_FOUND_DETAIL: Final = "Not found"
"""The one body an unknown, foreign or unbound-tenant public request gets."""

TENANT_REQUIRED_CODE: Final = "tenant_required"

PERM_GROUP: Final = MODULE_NAME
PERM_GROUP_KEY: Final = "images.permission_group"
PERM_VIEW: Final = "images.view"
PERM_CREATE: Final = "images.create"
PERM_PUBLISH: Final = "images.publish"
PERM_MANAGE: Final = "images.manage"
PERM_ORIGINALS: Final = "images.originals.view"
PERM_SETTINGS: Final = "images.settings"
PERMISSIONS: Final = (
    PERM_VIEW,
    PERM_CREATE,
    PERM_PUBLISH,
    PERM_MANAGE,
    PERM_ORIGINALS,
    PERM_SETTINGS,
)

# --- Public surface: GET only, so a later route cannot widen it by accident. ---

PUBLIC_METHODS: Final = frozenset({"GET", "HEAD"})
PUBLIC_COLLECTION_PREFIX: Final = f"{PUBLIC_PREFIX}/c/"
"""``/images/c/{slug}`` - the public collection page."""
PUBLIC_API_PREFIX: Final = f"{ROUTE_PREFIX_API}/public/"
"""Reserved for the anonymous serving, points and map routes the later tasks
mount (renditions, ``points``, PMTiles). Terminated with ``/`` so it can never
match ``/api/images`` itself."""
PUBLIC_PREFIXES: Final = (PUBLIC_COLLECTION_PREFIX, PUBLIC_API_PREFIX)

# --- Request-body ceilings: the routes that take an upload. ---

UPLOAD_ROUTE_PATTERNS: Final = (
    # POST /collections/{id}/images (multipart batch), POST .../imports/zip (relay)
    rf"^{ROUTE_PREFIX_API}/collections/[^/]+/(?:images|imports/zip)$",
    # POST /collections/{id}/imports with an inline base64 GeoJSON body
    rf"^{ROUTE_PREFIX_API}/collections/[^/]+/imports$",
)
UPLOAD_PREFIXES: Final = (f"{ROUTE_PREFIX_API}/uploads/",)
"""Relayed parts and ``/complete`` of a direct upload."""
UPLOAD_METHODS: Final = frozenset({"POST", "PUT"})
MULTIPART_OVERHEAD_BYTES: Final = 1024 * 1024
"""Headroom over ``upload_body_max_bytes`` for the multipart framing."""

MODULE_ATTR: Final = "images_module"
"""``app.state`` attribute holding the module instance."""
