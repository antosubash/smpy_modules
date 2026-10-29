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

DOWNLOAD_TIMEOUT_MAX: Final = 240
"""Ceiling of the ``download_timeout`` setting, in seconds: a minute under
``reconcile.CUTOFF``, and ``INLINE_ATTEMPTS`` tries plus their waits stay inside
``download.CLAIM_SECONDS`` (``tests/test_zip_fixes4.py`` checks both)."""

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
PUBLIC_API_ROUTER_PREFIX: Final = PUBLIC_API_PREFIX.removeprefix(ROUTE_PREFIX_API).rstrip("/")
"""``/public``: the anonymous router's prefix inside the module's API router."""

# --- Serving bytes (``/images/{id}/r/{size}``, ``/display``, ``/original``) ---

RENDITION_SIZE_MAX: Final = 50
"""``Rendition.size``'s column width; a longer path segment is a 422."""
DISPLAY_CONTENT_TYPE: Final = "image/jpeg"
"""Display copies and renditions are always JPEG (``storage_keys``)."""
ORIGINAL_FORBIDDEN_DETAIL: Final = "The original of this image is not available to you"

# --- The map: ``…/points`` and ``…/map.pmtiles`` (spec §5, ``sm_images.map``) ---

POINTS_LIMIT_DEFAULT: Final = 1000
POINTS_LIMIT_MAX: Final = 5000
"""A larger ``limit`` is clamped to this; ``next_cursor`` pages past it."""
BBOX_MAX_CHARS: Final = 200
BAD_BBOX_DETAIL: Final = "bbox must be minx,miny,maxx,maxy in degrees (lng -180..180, lat -90..90)"
PMTILES_CONTENT_TYPE: Final = "application/vnd.pmtiles"

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
DEFAULT_PIPELINE_STEPS: Final = ("exif", "renditions")
"""Core built-in steps a new collection enables."""
THUMB_SIZE: Final = "small"
"""The rendition the console gallery shows (a key of ``thumbnail_sizes``)."""
CANDIDATES_MAX: Final = 20
CANDIDATES_SCAN: Final = 100
"""How many directory hits are read before the tenant filter, so a page of
non-members does not hide the members behind them."""
SLUG_TAKEN_DETAIL: Final = "That slug is already in use"
PUBLISH_REQUIRED_DETAIL: Final = "Publishing a collection needs the images.publish permission"
GROUP_EXISTS_DETAIL: Final = "This collection already has a group with that key"
BAD_CURSOR_DETAIL: Final = "Invalid cursor"
DIRECTORY_UNAVAILABLE_CODE: Final = "user_directory_unavailable"
DIRECTORY_UNAVAILABLE_DETAIL: Final = "No user directory is installed on this host"

# --- Upload and ingest ---

SOURCE_UPLOAD: Final = "upload"
"""The ``source`` every client upload path (multipart, base64, direct) passes
to ``IngestService.add_image``, and so the default ``external_source``: the
three share one dedupe namespace."""
SOURCE_IMPORT: Final = "import"
"""The ``source`` (and so the ``external_source``) of every GeoJSON-imported
image: one dedupe namespace per collection, apart from client uploads."""
DEFAULT_FILENAME: Final = "upload"
FILENAME_MAX: Final = 255
EXTERNAL_SOURCE_MAX: Final = 100
EXTERNAL_ID_MAX: Final = 255
GROUP_KEY_MAX: Final = 200
GROUP_ROLE_MAX: Final = 50
GROUP_PREVIEW_MEMBERS: Final = 8
"""Members a group in the list carries (the first by role order); the detail has them all."""
GROUP_DETAIL_MEMBERS: Final = 500
REGROUP_BUDGET_SECONDS: Final = 5.0
"""How long planning a regroup may take before it is refused with nothing written."""
REGROUP_CHUNK: Final = 500
REGROUP_SYNC_MAX: Final = 2000
"""A collection with more images than this regroups as a background job."""
REGROUP_RELAUNCH_LIMIT: Final = 5
"""Reconcile relaunches without progress before a regroup job fails as ``stalled``."""
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
DIRECT_MAX_PARTS: Final = 10_000
"""Most parts one direct upload may list (S3's own limit)."""
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
CODE_UPLOAD_IN_PROGRESS: Final = "upload_in_progress"
CODE_UPLOAD_NOT_OPEN: Final = "upload_not_open"
CODE_GROUP_NOT_FOUND: Final = "group_not_found"
CODE_GROUP_EXISTS: Final = "group_exists"
CODE_INVALID_ROLE: Final = "invalid_role"
CODE_INVALID_PATTERN: Final = "invalid_pattern"
CODE_REGROUP_TOO_SLOW: Final = "regroup_too_slow"
CODE_REGROUP_ACTIVE: Final = "regroup_active"
CODE_ROLE_NEEDS_GROUP: Final = "role_needs_group"
CODE_CONFLICT: Final = "conflict"
CODE_QUOTA_EXCEEDED: Final = "quota_exceeded"
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
    CODE_UPLOAD_IN_PROGRESS,
    CODE_UPLOAD_NOT_OPEN,
    CODE_GROUP_NOT_FOUND,
    CODE_GROUP_EXISTS,
    CODE_INVALID_ROLE,
    CODE_INVALID_PATTERN,
    CODE_REGROUP_TOO_SLOW,
    CODE_REGROUP_ACTIVE,
    CODE_ROLE_NEEDS_GROUP,
    CODE_CONFLICT,
    CODE_QUOTA_EXCEEDED,
)
"""Every code an upload can answer with; each has a translated sentence."""

# Storage metering (decision 10, ``sm_images.billing``): a billing gauge in
# bytes. The key is a ``Plan.limits`` key, so renaming it orphans every limit.
METER_STORAGE: Final = "images.storage_bytes"
METER_STORAGE_LABEL_KEY: Final = "images.meters.storage_bytes"
BILLING_PACKAGE: Final = "sm_billing"
BILLING_USAGE_MODULE: Final = "sm_billing.contracts.metering"
BILLING_METERS_ATTR: Final = "billing_meters"
BILLING_USAGE_ATTR: Final = "billing_usage"

# --- Console pages (Inertia names: ``<module>/<file under pages/>``) ---

PAGE_COLLECTIONS: Final = f"{MODULE_NAME}/Collections"
PAGE_COLLECTION: Final = f"{MODULE_NAME}/Collection"
PAGE_IMAGE: Final = f"{MODULE_NAME}/Image"
PAGE_REVIEW: Final = f"{MODULE_NAME}/Review"
PAGE_PUBLIC_COLLECTION: Final = f"{MODULE_NAME}/PublicCollection"
PERM_SHARE: Final = "sharing.share"
"""The framework's share permission (``sharing.constants.PERM_SHARE``): the
share dialog is offered only to a holder who also owns the collection."""
