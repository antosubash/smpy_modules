"""The snapshot bundle's on-disk shape, named once.

A bundle is the same tree whether it is a directory under ``snapshot_root`` or
the inside of a ``.zip``. The only difference is that the zip carries the media
bytes under ``BLOBS_DIR`` while the server-side copy leaves them in the shared
blob store, so ten snapshots of an unchanged site hold one copy of its images.
"""

from __future__ import annotations

FORMAT_VERSION = 1
"""Bumped only for a change an older reader would misinterpret.

Checked on upload and again on restore: an unknown version is refused with a
clear message rather than half-understood.
"""

MANIFEST_NAME = "manifest.json"
LAYOUT_NAME = "layout.json"
REDIRECTS_NAME = "redirects.json"
PAGES_DIR = "pages"
MEDIA_DIR = "media"
MEDIA_INDEX_NAME = "index.json"
BLOBS_DIR = "blobs"

ASSET_SCHEME = "asset://"
"""Sentinel standing in for a media URL inside bundled content.

A media URL embeds a host-local UUID filename, so serialising one verbatim
would produce a bundle whose images 404 everywhere but the host that wrote it.
"""
