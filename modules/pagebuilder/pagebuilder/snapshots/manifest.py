"""The bundle manifest: what wrote a bundle, and what it contains.

``manifest.json`` is the one file every reader opens first, so it is the file
that has to answer "can I read this?" before anything else is trusted. Its
format is documented for people in ``docs/bundle-format.md``; this module is
the reader and writer, and the two must not disagree.

Two version numbers, deliberately:

* ``format_version`` is the **major**. A reader refuses one outside
  :data:`~pagebuilder.snapshots.format.READABLE_VERSIONS`, because a major
  bump means an older reader would misread the documents, not merely miss
  something. It stays an integer so builds released before this file still
  read bundles written after it.
* ``format_minor`` counts additive changes — new keys an older reader can
  ignore. It is never checked; recording it only tells a person which build
  shape they are looking at.

``contents`` lists the bundle's sections. Pagebuilder's own documents are the
``pagebuilder`` section and keep the root-level paths they have always had.
Another module contributing to a bundle (#80 — not built) would add a section
of its own whose files live under ``<section>/``, and mark it ``required`` if
restoring the bundle without it would leave a site incoherent. A reader
refuses a required section it does not know and ignores an optional one, so
a bundle can grow without every older host refusing it.
"""

from __future__ import annotations

import importlib.metadata
import re
from datetime import UTC, datetime
from typing import Any

from pagebuilder.snapshots.format import (
    BLOBS_DIR,
    FORMAT_VERSION,
    LAYOUT_NAME,
    MANIFEST_NAME,
    MEDIA_DIR,
    PAGES_DIR,
    READABLE_VERSIONS,
    REDIRECTS_NAME,
    is_readable,
)
from pagebuilder.snapshots.validate import BundleError

FORMAT_NAME = "simple-module.content-bundle"
"""Names the format, so a stray ``manifest.json`` from anything else is not
mistaken for one. Absent from bundles written before the manifest was
versioned; present, it must match."""

FORMAT_MINOR = 1
"""Minor 1 added ``format``, ``format_minor``, ``source``, ``tenant`` and
``contents`` to the manifest. Nothing else in the bundle changed."""

PAGEBUILDER_SECTION = "pagebuilder"
PAGEBUILDER_SECTION_VERSION = 1
_SECTION_VERSIONS: dict[str, frozenset[int]] = {PAGEBUILDER_SECTION: frozenset({1})}
"""The sections this build restores, and which of their versions."""

PAGEBUILDER_PATHS = (LAYOUT_NAME, REDIRECTS_NAME, f"{PAGES_DIR}/", f"{MEDIA_DIR}/")
"""Every root-level path pagebuilder reads. A file in a bundle belongs to
exactly one section, and these are the pagebuilder section's, whatever its
manifest entry says."""

RESERVED_SECTION_NAMES = frozenset(
    {
        PAGEBUILDER_SECTION,
        PAGES_DIR,
        MEDIA_DIR,
        BLOBS_DIR,
        *(name.removesuffix(".json") for name in (LAYOUT_NAME, REDIRECTS_NAME, MANIFEST_NAME)),
    }
)
"""Names no other section may take. A section's files live under
``<section>/``, so one named ``pages`` would have its files read as pages."""

_SECTION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PACKAGE = "simple_module_pagebuilder"


def _package_version() -> str | None:
    try:
        return importlib.metadata.version(_PACKAGE)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - always installed
        return None


def manifest_header(tenant: str | None) -> dict[str, Any]:
    """The keys every manifest this build writes starts with.

    *tenant* is the tenant the content was captured from. It is a label, not
    a constraint: moving content between hosts — and so between tenants — is
    what a bundle is for, so a reader never refuses on it.
    """
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "format_minor": FORMAT_MINOR,
        "created_at": datetime.now(UTC).isoformat(),
        "source": {
            "module": PAGEBUILDER_SECTION,
            "package": _PACKAGE,
            "version": _package_version(),
        },
        "tenant": tenant,
        "contents": [
            {
                "section": PAGEBUILDER_SECTION,
                "version": PAGEBUILDER_SECTION_VERSION,
                "required": True,
                "paths": list(PAGEBUILDER_PATHS),
            }
        ],
    }


def _major(payload: dict[str, Any]) -> int:
    if "format_version" not in payload:
        # Unversioned: the shape version 1 already had. Everything this module
        # has ever written carries the key, so this is a hand-made bundle —
        # which the document checks downstream still hold to v1's rules.
        return 1
    version = payload["format_version"]
    # `bool` is an `int`, and `True == 1`: a manifest saying `true` is not v1.
    if not isinstance(version, int) or isinstance(version, bool) or not is_readable(version):
        readable = ", ".join(str(v) for v in sorted(READABLE_VERSIONS))
        raise BundleError(
            f"unsupported bundle format version {version!r}; this build reads "
            f"versions {readable}. Upgrade pagebuilder on this host to restore it."
        )
    return version


def _check_path(section: str, path: str) -> None:
    """A declared path is relative, forward-slashed and never climbs.

    Checked as written rather than normalised: ``news/../pages/`` normalises
    to a path inside ``pages/``, and a reader that compared prefixes before
    normalising would hand it to the news section.
    """
    parts = path.removesuffix("/").split("/")
    if (
        not path
        or "\\" in path
        or path.startswith("/")
        or ":" in parts[0]
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise BundleError(f"section {section!r} declares an unsafe path: {path!r}")


def _check_section(entry: Any, seen: set[str]) -> None:
    if not isinstance(entry, dict):
        raise BundleError("manifest contents entry is not an object")
    name = entry.get("section")
    if not isinstance(name, str) or not _SECTION_NAME.match(name):
        raise BundleError(f"manifest contents entry has no valid section name: {name!r}")
    if name in seen:
        raise BundleError(f"manifest lists section {name!r} twice")
    seen.add(name)
    version = entry.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise BundleError(f"section {name!r} has no integer version")
    required = entry.get("required", True)
    if not isinstance(required, bool):
        raise BundleError(f"section {name!r} has a non-boolean 'required'")
    paths = entry.get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise BundleError(f"section {name!r} paths must be a list of strings")
    for path in paths:
        _check_path(name, path)

    known = _SECTION_VERSIONS.get(name)
    if known is None:
        if required:
            raise BundleError(
                f"bundle requires the {name!r} section, which this host cannot restore"
            )
        # Ignored, but confined: a section that claimed pagebuilder's paths
        # would have its files read as pages.
        if name in RESERVED_SECTION_NAMES:
            raise BundleError(f"section name {name!r} is reserved for pagebuilder")
        stray = [p for p in paths if not p.startswith(f"{name}/")]
        if stray:
            raise BundleError(f"section {name!r} claims paths outside {name}/: {stray}")
        return
    if name == PAGEBUILDER_SECTION:
        stray = [p for p in paths if p not in PAGEBUILDER_PATHS]
        if stray:
            raise BundleError(f"the pagebuilder section claims paths it does not own: {stray}")
    if version not in known:
        raise BundleError(f"unsupported version {version} of the {name!r} section")


def check_manifest(payload: Any) -> dict[str, Any]:
    """Validate *payload* as a manifest; return it with its major filled in.

    Raises :class:`BundleError` — a 422 at the upload boundary — for anything
    this build cannot honestly restore. A manifest without ``contents`` (every
    bundle written before minor 1) is read as the pagebuilder section alone,
    which is exactly what those bundles hold.
    """
    if not isinstance(payload, dict):
        raise BundleError("manifest.json is not an object")
    major = _major(payload)
    if "format" in payload and payload["format"] != FORMAT_NAME:
        raise BundleError(f"manifest.json describes a {payload['format']!r}, not a content bundle")
    contents = payload.get("contents")
    if contents is not None:
        if not isinstance(contents, list):
            raise BundleError("manifest contents is not a list")
        seen: set[str] = set()
        for entry in contents:
            _check_section(entry, seen)
        if PAGEBUILDER_SECTION not in seen:
            raise BundleError("bundle has no pagebuilder section to restore")
    return {**payload, "format_version": major}


def _owns(paths: list[str] | tuple[str, ...], member: str) -> bool:
    return any(member.startswith(p) if p.endswith("/") else member == p for p in paths)


def check_members(manifest: dict[str, Any], members: list[str]) -> None:
    """Every archive member except the manifest belongs to exactly one section.

    The manifest's paths are only a claim; this holds them to what the zip
    actually carries. A file no section owns is one nothing will read — most
    likely a bundle assembled by hand from the wrong tree — and a file two
    sections own is one of them reading the other's data.
    """
    sections: dict[str, list[str] | tuple[str, ...]] = {PAGEBUILDER_SECTION: PAGEBUILDER_PATHS}
    for entry in manifest.get("contents") or []:
        if entry["section"] != PAGEBUILDER_SECTION:
            sections[entry["section"]] = entry.get("paths", [])
    for member in members:
        if member == MANIFEST_NAME:
            continue
        owners = [name for name, paths in sections.items() if _owns(paths, member)]
        if not owners:
            raise BundleError(f"bundle file {member!r} belongs to no section in the manifest")
        if len(owners) > 1:
            raise BundleError(f"bundle file {member!r} is claimed by sections {owners}")
