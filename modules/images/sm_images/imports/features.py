"""One GeoJSON feature to one import item: :func:`extract`.

Every feature becomes exactly one ``ImportItem`` - a usable one ``pending``, an
unusable one ``failed`` with a constant code - so the job's counters always add
up to its feature count and a replay can tell what it already recorded. One
malformed feature never fails the import (per-feature isolation, as in the
portal): anything unexpected is ``invalid_feature``.

**External ids.** The mapped property when it has a value; otherwise, in URL
mode, ``sha256(url)[:32]`` (the portal's default), and in base64 mode
``sha256("<job>:<feature index>")`` - stable across a replay of the same job, so
a resumed run finds what a killed one created (static finding 5: the portal's
fallback also hashed the encoded text, so the same image re-encoded got another
id; content dedupe is ``dedupe_by_hash``'s job, on the decoded bytes).
"""

from __future__ import annotations

import hashlib
import json
import logging
import posixpath
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from urllib.parse import unquote, urlsplit

from sm_images import constants
from sm_images.imports.filename_pattern import canonical_role, group_key, match_group
from sm_images.imports.mapping import Mapping
from sm_images.imports.values import coordinates, lookup, parse_datetime
from sm_images.models.enums import ImportKind

__all__ = [
    "PARSE_CODES",
    "URL_MAX",
    "Parsed",
    "base64_external_id",
    "extract",
    "url_external_id",
    "url_filename",
]

logger = logging.getLogger(__name__)

URL_MAX: Final = 2000
PARSE_CODES: Final = frozenset(
    {
        "missing_url",
        "invalid_url",
        "missing_image",
        "invalid_external_id",
        "invalid_feature",
        "feature_too_large",
    }
)
"""Failures decided by the feature itself: a retry would only repeat them, so
retry-failed never resets them."""


@dataclass
class Parsed:
    index: int
    error: str | None = None
    url: str | None = None
    payload: str | None = None
    """Base64 mode: the encoded image, held only while its chunk is processed."""
    external_id: str | None = None
    filename: str | None = None
    lat: float | None = None
    lng: float | None = None
    captured_at: datetime | None = None
    group_key: str | None = None
    group_role: str | None = None
    properties: dict[str, Any] | None = None

    @property
    def size(self) -> int:
        return len(self.payload) if self.payload else 0


def url_external_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def base64_external_id(job_id: uuid.UUID, index: int) -> str:
    return hashlib.sha256(f"{job_id}:{index}".encode()).hexdigest()


def _text_id(raw: Any) -> str | None:
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    text = str(raw).strip()
    return text or None


def _bounded(properties: dict[str, Any], drop: str | None) -> dict[str, Any] | None:
    kept = {k: v for k, v in properties.items() if k != drop}
    if not kept:
        return None
    size = len(json.dumps(kept, separators=(",", ":"), default=str).encode())
    return kept if size <= constants.PROPERTIES_MAX_BYTES else None


def url_filename(url: str) -> str:
    return unquote(posixpath.basename(urlsplit(url).path)) or "image"


def _group(
    props: dict[str, Any], mapping: Mapping, filename: str, roles: Sequence[str]
) -> tuple[str | None, str | None]:
    if mapping.group_key_prop:
        key = group_key(lookup(props, mapping.group_key_prop))
        if key is None:
            return None, None
        return key, canonical_role(lookup(props, mapping.group_role_prop), roles)
    if mapping.filename_pattern:
        return match_group(mapping.filename_pattern, filename, roles)
    return None, None


def _source(parsed: Parsed, props: dict[str, Any], kind: ImportKind, mapping: Mapping) -> bool:
    """Fill the url or payload; ``False`` (with ``error`` set) when unusable."""
    if kind is ImportKind.GEOJSON_URL:
        url = lookup(props, mapping.url_prop)
        if not isinstance(url, str) or not url.strip():
            parsed.error = "missing_url"
            return False
        url = url.strip()
        if len(url) > URL_MAX or not url.lower().startswith(("http://", "https://")):
            parsed.error = "invalid_url"
            return False
        parsed.url = url
        return True
    data = lookup(props, mapping.image_prop)
    if not isinstance(data, str) or not data.strip():
        parsed.error = "missing_image"
        return False
    parsed.payload = data
    return True


def _extract(
    feature: Any, index: int, kind: ImportKind, mapping: Mapping, job_id: uuid.UUID, roles
) -> Parsed:
    parsed = Parsed(index)
    if not isinstance(feature, dict):
        parsed.error = "invalid_feature"
        return parsed
    raw_props = feature.get("properties")
    props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
    geometry = feature.get("geometry")
    if not _source(parsed, props, kind, mapping):
        return parsed
    given = _text_id(lookup(props, mapping.external_id_prop))
    if given is not None and len(given) > constants.EXTERNAL_ID_MAX:
        parsed.error = "invalid_external_id"
        return parsed
    if parsed.url is not None:
        parsed.external_id = given or url_external_id(parsed.url)
        parsed.filename = url_filename(parsed.url)
    else:
        parsed.external_id = given or base64_external_id(job_id, index)
        parsed.filename = given or f"feature-{index}"
    parsed.lat, parsed.lng = coordinates(
        props, geometry if isinstance(geometry, dict) else None, mapping.lat_prop, mapping.lng_prop
    )
    parsed.captured_at = parse_datetime(lookup(props, mapping.datetime_prop))
    parsed.group_key, parsed.group_role = _group(props, mapping, parsed.filename, roles)
    drop = mapping.image_prop if kind is ImportKind.GEOJSON_BASE64 else None
    parsed.properties = _bounded(props, drop)
    return parsed


def extract(
    feature: Any,
    index: int,
    *,
    kind: ImportKind,
    mapping: Mapping,
    job_id: uuid.UUID,
    roles: Sequence[str] = (),
) -> Parsed:
    """The item ``feature`` (at absolute ``index``) becomes; never raises."""
    try:
        return _extract(feature, index, kind, mapping, job_id, roles)
    except Exception:
        logger.warning("images.import.feature_failed index=%s", index, exc_info=True)
        return Parsed(index, error="invalid_feature")
