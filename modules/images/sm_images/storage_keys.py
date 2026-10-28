"""The one object-key layout (spec §1). Pure functions; nothing here touches storage.

``images/<tenant>/<collection>/<image>/original.<ext>``, ``display.<gen>.jpg``,
``r/<size>.<gen>.jpg``, ``images/<tenant>/<collection>/map.pmtiles`` and
``images/<tenant>/imports/<job>/<name>``. Display and rendition keys carry the
display generation (for caches) **and the attempt** - the step run's lease
token - because two attempts can load the same generation: a stale worker and
the one that reclaimed its lease. The DB fence decides which is published; the
attempt in the key is what stops the loser overwriting or deleting the
winner's bytes.
"""

from __future__ import annotations

import re

ROOT = "images"
_EXT_UNSAFE = re.compile(r"[^a-z0-9]")
_ATTEMPT_UNSAFE = re.compile(r"[^a-z0-9]")


def _ext(ext: str) -> str:
    return _EXT_UNSAFE.sub("", ext.lower())[:8] or "bin"


def _image_prefix(tenant: str, collection: str, image: str) -> str:
    return f"{ROOT}/{tenant}/{collection}/{image}"


def original_key(tenant: str, collection: str, image: str, ext: str) -> str:
    return f"{_image_prefix(tenant, collection, image)}/original.{_ext(ext)}"


def _attempt(attempt: str) -> str:
    return _ATTEMPT_UNSAFE.sub("", attempt.lower())[:32] or "0"


def display_key(tenant: str, collection: str, image: str, generation: int, attempt: str) -> str:
    return (
        f"{_image_prefix(tenant, collection, image)}/display.{generation}.{_attempt(attempt)}.jpg"
    )


def rendition_key(
    tenant: str, collection: str, image: str, size: str, generation: int, attempt: str
) -> str:
    prefix = _image_prefix(tenant, collection, image)
    return f"{prefix}/r/{size}.{generation}.{_attempt(attempt)}.jpg"


def map_key(tenant: str, collection: str) -> str:
    return f"{ROOT}/{tenant}/{collection}/map.pmtiles"


def import_key(tenant: str, job: str, name: str) -> str:
    return f"{ROOT}/{tenant}/imports/{job}/{name}"


def image_prefix(tenant: str, collection: str, image: str) -> str:
    """Everything one image ever stored is under this (trailing ``/`` included)."""
    return f"{_image_prefix(tenant, collection, image)}/"


def collection_prefix(tenant: str, collection: str) -> str:
    return f"{ROOT}/{tenant}/{collection}/"


def import_prefix(tenant: str, job: str) -> str:
    return f"{ROOT}/{tenant}/imports/{job}/"
