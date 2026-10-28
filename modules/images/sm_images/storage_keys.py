"""The one object-key layout (spec §1). Pure functions; nothing here touches storage.

``images/<tenant>/<collection>/<image>/original.<ext>``, ``display.<gen>.jpg``,
``r/<size>.<gen>.jpg``, ``images/<tenant>/<collection>/map.pmtiles`` and
``images/<tenant>/imports/<job>/<name>``. Display and rendition keys carry a
generation so a rewrite never overwrites the object a stale worker may still be
reading or about to delete.
"""

from __future__ import annotations

import re

ROOT = "images"
_EXT_UNSAFE = re.compile(r"[^a-z0-9]")


def _ext(ext: str) -> str:
    return _EXT_UNSAFE.sub("", ext.lower())[:8] or "bin"


def _image_prefix(tenant: str, collection: str, image: str) -> str:
    return f"{ROOT}/{tenant}/{collection}/{image}"


def original_key(tenant: str, collection: str, image: str, ext: str) -> str:
    return f"{_image_prefix(tenant, collection, image)}/original.{_ext(ext)}"


def display_key(tenant: str, collection: str, image: str, generation: int) -> str:
    return f"{_image_prefix(tenant, collection, image)}/display.{generation}.jpg"


def rendition_key(tenant: str, collection: str, image: str, size: str, generation: int) -> str:
    return f"{_image_prefix(tenant, collection, image)}/r/{size}.{generation}.jpg"


def map_key(tenant: str, collection: str) -> str:
    return f"{ROOT}/{tenant}/{collection}/map.pmtiles"


def import_key(tenant: str, job: str, name: str) -> str:
    return f"{ROOT}/{tenant}/imports/{job}/{name}"
