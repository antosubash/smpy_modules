"""PageBuilder's media and snapshot storage settings, split out of ``settings``.

:class:`~pagebuilder.core.settings.PagebuilderSettings` inherits these, so a
field here is read, stored and edited exactly like one declared there: from
the database through the Settings screen, never from the environment. Split
by responsibility when ``settings.py`` reached the file-size warning line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See ``settings``' docstring."""


class MediaSettings(BaseSettings):
    # ``use_attribute_docstrings`` is what puts the prose under each field on
    # the Settings screen: the admin UI renders ``FieldInfo.description``, and
    # without this every field would arrive there unexplained. Subclasses
    # inherit it.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Init kwargs only — no env, no ``.env``, no secrets directory.

        The hydrator passes stored overrides as keyword arguments, so this
        leaves exactly two answers for any field: what the database says, or
        the default declared here. Dropping the env sources rather than merely
        not documenting them is deliberate — a stray ``SM_PAGEBUILDER_*`` left
        in a shell or a deploy manifest would otherwise quietly outrank the
        value an operator can see and edit on the Settings screen.
        """
        return (init_settings,)

    media_root: Path = Field(
        default=Path("var/pagebuilder/media"), json_schema_extra=_RESTART
    )
    """Filesystem directory where uploaded media is stored.

    Relative paths are anchored to the project root (``SM_PROJECT_ROOT``
    when set, else the nearest directory holding a ``pyproject.toml``,
    ``.env`` or ``alembic.ini``) — never the bare process cwd, which made
    two differently-launched processes read and write different media
    directories against one database. Created if it doesn't exist.
    """

    media_url_prefix: str = Field(
        default="/media/pagebuilder", json_schema_extra=_RESTART
    )
    """URL prefix the media directory is mounted at."""

    media_max_bytes: int = 10 * 1024 * 1024
    """Reject uploads larger than this (default 10 MB)."""

    media_allowed_content_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    )
    """Content-types accepted by the upload endpoint.

    SVG is intentionally excluded from the default allowlist: SVG is XML
    and can embed ``<script>`` tags, yielding stored-XSS the moment a
    user views the file under a same-origin URL. Hosts that need SVG
    should add it explicitly on the Settings screen and pair it with their
    own sanitizer.
    """

    media_thumbnail_widths: tuple[int, ...] = (320, 640, 1280, 1920)
    """Pixel widths to generate webp thumbnails for on upload.

    Only widths *strictly less than* the source width produce a derivative
    — there's no point upscaling a 600px hero to 1920px. Set to an empty
    tuple to disable thumbnail generation entirely.
    """

    media_webp_quality: int = 82
    """Pillow encoder ``quality`` for webp thumbnails (0-100)."""

    snapshot_root: Path = Path("var/pagebuilder/snapshots")
    """Filesystem directory holding content snapshots and their shared blobs.

    Anchored to the project root exactly like :attr:`media_root`. A
    cwd-relative default is what made two differently-launched processes
    read and write different media directories against one database
    (issue #14); snapshots would fail the same way, and more quietly.
    """

    snapshot_max_upload_bytes: int = 200 * 1024 * 1024
    """Reject uploaded bundles larger than this (default 200 MB).

    Far larger than ``media_max_bytes`` because a bundle legitimately
    contains a whole media library, not one image.
    """

    snapshot_max_extracted_bytes: int = 1024 * 1024 * 1024
    """Reject a bundle that expands to more than this (default 1 GB).

    Separate from ``snapshot_max_upload_bytes`` because the compressed size
    bounds nothing: a bundle's media is already-compressed images that barely
    shrink, but a crafted archive of repetitive bytes reaches roughly 1000:1,
    so a body inside the upload cap can still fill the disk on extraction.
    """

    media_strip_metadata: bool = True
    """Remove EXIF, XMP and IPTC metadata from uploaded JPEG, PNG and WebP files.

    A photo from a phone or camera carries GPS coordinates, the device and its
    serial number, the capture time and sometimes the owner's name, and the
    original is published as uploaded. With this on, the upload is re-saved
    without that metadata: its EXIF orientation is applied first, so the
    picture does not turn sideways, and its ICC colour profile is kept.
    Animated images (GIF, animated WebP or PNG) are stored untouched.

    Turn it off for a site that publishes photography and wants its copyright
    and camera fields kept. Applies to uploads made after the change; files
    already in the library keep whatever they carried.
    """
