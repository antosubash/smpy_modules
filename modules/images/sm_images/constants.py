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
#: The framework modules images builds on, by ``ModuleMeta.name``: shares
#: (``sharing.policy`` in the access policy), the storage backend, and the
#: background workers the pipeline runs on.
_MODULE_SHARING: Final = "Sharing"
_MODULE_FILE_STORAGE: Final = "FileStorage"
_MODULE_BACKGROUND_TASKS: Final = "BackgroundTasks"
DEPENDS_ON: Final = (
    _MODULE_SETTINGS,
    _MODULE_SHARING,
    _MODULE_FILE_STORAGE,
    _MODULE_BACKGROUND_TASKS,
)

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
    # POST /collections/{id}/images (multipart batch), .../images/base64, .../imports/zip (relay)
    rf"^{ROUTE_PREFIX_API}/collections/[^/]+/(?:images|images/base64|imports/zip)$",
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

# --- Collections ---

SLUG_MAX: Final = 80
SLUG_PATTERN: Final = r"^[a-z0-9-]{1,80}$"
SLUG_FALLBACK: Final = "collection"
NAME_MAX: Final = 200
DESCRIPTION_MAX: Final = 2000
PAGE_DEFAULT: Final = 25
PAGE_MAX: Final = 100
COLLECTION_FILTERS: Final = ("owned", "shared", "internal", "public", "all")
CANDIDATES_MAX: Final = 20
CANDIDATES_SCAN: Final = 100
"""How many directory hits are read before the tenant filter, so a page of
non-members does not hide the members behind them."""
SLUG_TAKEN_DETAIL: Final = "That slug is already in use"
PUBLISH_REQUIRED_DETAIL: Final = "Publishing a collection needs the images.publish permission"
BAD_CURSOR_DETAIL: Final = "Invalid cursor"
DIRECTORY_UNAVAILABLE_CODE: Final = "user_directory_unavailable"
DIRECTORY_UNAVAILABLE_DETAIL: Final = "No user directory is installed on this host"

# --- Upload and ingest ---

SOURCE_UPLOAD: Final = "upload"
"""The ``source`` every client upload path (multipart, base64, direct) passes
to ``IngestService.add_image``, and so the default ``external_source``: the
three share one dedupe namespace."""
DEFAULT_FILENAME: Final = "upload"
FILENAME_MAX: Final = 255
EXTERNAL_SOURCE_MAX: Final = 100
EXTERNAL_ID_MAX: Final = 255
GROUP_KEY_MAX: Final = 200
GROUP_ROLE_MAX: Final = 50
PROPERTIES_MAX_BYTES: Final = 16 * 1024
"""Largest ``properties`` object one image's metadata may carry, as compact JSON."""
METADATA_MAX_BYTES: Final = 1024 * 1024
"""Largest ``metadata`` form field of a multipart batch."""
READ_CHUNK_BYTES: Final = 1024 * 1024

DIRECT_PART_BYTES: Final = 8 * 1024 * 1024
"""Part size of a direct upload; above S3's 5 MiB floor for every part but the last."""
DIRECT_UPLOAD_TTL_SECONDS: Final = 24 * 3600
"""How long a direct-upload token (and so the upload) stays usable."""
DIRECT_PRESIGN_TTL_SECONDS: Final = 3600
DIRECT_TOKEN_SALT: Final = "sm_images.direct-upload.v1"
DIRECT_TOKEN_MAX: Final = 2048
UPLOADS_PATH: Final = "/uploads"
PART_PATH: Final = f"{ROUTE_PREFIX_API}{UPLOADS_PATH}/{{upload_id}}/parts/{{part_no}}"
"""Where a backend that cannot presign (filesystem) has the client PUT each part."""

# Error codes: the ``code`` of an ``ImagesError`` body. The console maps each to
# ``images.errors.<code>`` in its catalogues (pagebuilder #221's pattern).
CODE_UNSUPPORTED_TYPE: Final = "unsupported_type"
CODE_TOO_MANY_PIXELS: Final = "image_too_many_pixels"
CODE_FILE_TOO_LARGE: Final = "file_too_large"
CODE_USE_DIRECT_UPLOAD: Final = "use_direct_upload"
CODE_BATCH_TOO_LARGE: Final = "batch_too_large"
CODE_INVALID_METADATA: Final = "invalid_metadata"
CODE_INVALID_BASE64: Final = "invalid_base64"
CODE_UPLOAD_NOT_FOUND: Final = "upload_not_found"
CODE_PARTS_MISMATCH: Final = "parts_mismatch"
CODE_DIRECT_UNSUPPORTED: Final = "direct_upload_unsupported"
CODE_UPLOAD_FAILED: Final = "upload_failed"
ERROR_CODES: Final = (
    CODE_UNSUPPORTED_TYPE,
    CODE_TOO_MANY_PIXELS,
    CODE_FILE_TOO_LARGE,
    CODE_USE_DIRECT_UPLOAD,
    CODE_BATCH_TOO_LARGE,
    CODE_INVALID_METADATA,
    CODE_INVALID_BASE64,
    CODE_UPLOAD_NOT_FOUND,
    CODE_PARTS_MISMATCH,
    CODE_DIRECT_UNSUPPORTED,
    CODE_UPLOAD_FAILED,
)
"""Every code an upload can answer with; each has a translated sentence."""
