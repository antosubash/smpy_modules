"""The snapshot bundle's on-disk shape, named once.

A bundle is the same tree whether it is a directory under ``snapshot_root`` or
the inside of a ``.zip``. The only difference is that the zip carries the media
bytes under ``BLOBS_DIR`` while the server-side copy leaves them in the shared
blob store, so ten snapshots of an unchanged site hold one copy of its images.
"""

from __future__ import annotations

FORMAT_VERSION = 2
"""The version this build writes.

Bumped only for a change an older reader would misinterpret. Version 2 keys a
page by ``(locale, slug)`` rather than by ``slug`` alone, because a slug is
only unique within a language — a v1 reader handed a bilingual bundle would
see two documents claiming one page.

Checked on upload and again on restore: a version outside
:data:`READABLE_VERSIONS` is refused with a clear message rather than
half-understood.
"""

READABLE_VERSIONS: frozenset[int] = frozenset({1, 2})
"""Versions this build can restore, which is wider than the one it writes.

A v1 bundle predates the ``locale`` column, so every page in one is in the
default content locale — that is not a guess, it is what the schema
guaranteed when the bundle was written. Reading it that way costs one
``or`` in :func:`~pagebuilder.snapshots.pages.payload_locale`, where refusing
it would strand every snapshot taken before this build for no gain.
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

def is_readable(version: object) -> bool:
    """Whether this build can restore a bundle written at *version*.

    A predicate rather than the set itself, so the two gates — the upload
    boundary and the restore request — cannot drift into different notions of
    readable, and so widening the range stays one edit here.
    """
    return version in READABLE_VERSIONS
