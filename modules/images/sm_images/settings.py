"""Images module settings - stored in the database, edited in Settings.

There is no ``SM_IMAGES_*`` environment variable and no ``.env`` stanza:
:class:`~simple_module_core.settings_base.DbBackedSettings` drops every source
pydantic-settings would otherwise consult, leaving the field defaults below and
whatever the settings module has stored. The module registers this class in
``register_settings`` via ``register_module_settings``, the host hydrates it
from the DB at lifespan start, and the Settings screen writes it back. SYSTEM
scope: one configuration for the whole deployment, shared by every tenant.

The two fields read while booting are declared on the base class
:class:`~sm_images.settings_boot.BootSettings` and carry ``requires_restart``.
Everything else is read per request, or per task in a worker.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from sm_images.constants import DOWNLOAD_TIMEOUT_MAX
from sm_images.map_style import DEFAULT_STYLE_URL, validate_style_url
from sm_images.settings_boot import BootSettings

__all__ = ["ImagesSettings"]

_MIB = 2**20
_GIB = 2**30


class ImagesSettings(BootSettings):
    # ``use_attribute_docstrings`` puts the prose under each field on the
    # Settings screen: the admin UI renders ``FieldInfo.description``.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    anonymize_weights_path: str = ""
    """Directory holding the ``anonymize`` step's detector weights.

    It must contain ``face.onnx`` (a YuNet face model) and ``plate.onnx`` (an
    end-to-end YOLOv9 plate model, open-image-models layout).
    Empty (the default) downloads pinned, checksummed weights once, on first
    use, to ``~/.cache/simple_module_images/models`` on each worker. The
    weights are not bundled in the wheel. Read by every anonymize run from the
    worker's settings, so a change applies within about 30 seconds, no restart.
    """

    max_image_bytes: int = Field(default=50 * _MIB, ge=1)
    """Largest single image accepted, in bytes."""

    batch_max: int = Field(default=50, ge=1)
    """Most files one multipart upload request may carry."""

    upload_body_max_bytes: int = Field(default=100 * _MIB, ge=1)
    """Request-body ceiling of the upload routes, in bytes (multipart framing
    is added on top). Read per request."""

    direct_upload_threshold: int = Field(default=20 * _MIB, ge=1)
    """A file over this size must use a direct (presigned) upload, in bytes."""

    max_open_uploads_per_tenant: int = Field(default=20, ge=1)
    """Most direct and ZIP uploads one tenant may have open at once. Opening one
    is also refused when the storage gauge plus the declared sizes of the
    tenant's open uploads would not fit the plan (with billing installed)."""

    zip_max_bytes: int = Field(default=2 * _GIB, ge=1)
    """Largest ZIP archive accepted for import, in bytes."""

    zip_max_entries: int = Field(default=10_000, ge=1)
    """Most entries an archive may declare."""

    zip_max_entry_bytes: int = Field(default=200 * _MIB, ge=1)
    """Largest single decompressed entry, in bytes."""

    zip_max_total_bytes: int = Field(default=8 * _GIB, ge=1)
    """Most decompressed bytes an archive may produce in total."""

    zip_max_ratio: int = Field(default=200, ge=1)
    """Highest compression ratio an entry may show before it is refused."""

    geojson_max_features: int = Field(default=1_000_000, ge=1)
    """Most features one GeoJSON source may hold."""

    geojson_max_bytes: int = Field(default=2 * _GIB, ge=1)
    """Largest GeoJSON source, in bytes."""

    geojson_max_feature_bytes: int = Field(default=60 * _MIB, ge=1)
    """Largest single feature of a GeoJSON source (roughly, in bytes of its
    values); a larger one fails as ``feature_too_large`` without being built.
    The default fits a 50 MiB image as base64 (4/3 larger)."""

    download_concurrency_per_domain: int = Field(default=4, ge=1)
    """Simultaneous image downloads from one host during an import."""

    download_concurrency_total: int = Field(default=32, ge=1)
    """Simultaneous image downloads across all hosts during an import."""

    download_timeout: int = Field(default=60, ge=1, le=DOWNLOAD_TIMEOUT_MAX)
    """Seconds one image download may take (at most 240: under reconcile's
    5-minute stale cutoff, and three tries fit inside an item's claim)."""

    thumbnail_sizes: dict[str, int] = Field(
        default_factory=lambda: {"marker": 64, "small": 160, "medium": 400, "large": 1024}
    )
    """Rendition name to longest edge in pixels."""

    dedupe_by_hash: bool = False
    """Skip an upload whose content hash already exists in the collection."""

    map_rebuild_threshold_pct: int = Field(default=5, ge=1)
    """Rebuild a collection's map tiles once this percentage of points changed.
    At least 1: a 0 would make every single change due."""

    map_rebuild_threshold_abs: int = Field(default=100, ge=1)
    """...or once this many points changed, whichever comes first (at least 1)."""

    map_style_url: str = DEFAULT_STYLE_URL
    """MapLibre style drawn under the map's points (an ``https://`` URL).

    The default is OpenFreeMap's Positron: free, no API key, OpenStreetMap
    data. Privacy trade-off: every viewer's browser, on the console and on
    public pages, requests the style and the tiles for the area it looks at
    from that host, which so learns their IP address and where they look.
    Empty draws a flat background with no third-party request at all. The
    style's origin is added to the Content-Security-Policy; a style that loads
    tiles from another host needs that host on the same origin. Read per page
    load, no restart.
    """

    janitor_grace_days: int = Field(default=7, ge=0)
    """Days an unreferenced object is kept before the janitor reaps it."""

    step_output_max_bytes: int = Field(default=65536, ge=1)
    """Largest JSON a pipeline step may store as its output, in bytes."""

    step_lease_seconds: int = Field(default=1800, ge=1)
    """Seconds a step run may hold its lease before another worker reclaims it."""

    @field_validator("map_style_url")
    @classmethod
    def _style_url(cls, value: str) -> str:
        return validate_style_url(value)
