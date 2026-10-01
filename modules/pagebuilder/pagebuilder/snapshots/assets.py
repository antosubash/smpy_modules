"""Translating media URLs to and from the portable ``asset://`` sentinel.

A media URL is ``{media_url_prefix}/{filename}`` where the filename is a UUID
assigned at upload — host-local by construction. Capture therefore replaces
every such URL with ``asset://<bundle name>``, and restore puts back whatever
URL the file was given on *this* host.

Only URLs that resolve to a row in the media library are rewritten: the
mapping is built from the media table rather than guessed from string shape,
so module static mounts (``/<module>/static/...``), external URLs and in-site
links pass through untouched.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pagebuilder.snapshots.format import ASSET_SCHEME


def to_sentinels(node: Any, url_to_name: dict[str, str]) -> Any:
    """Replace known media URLs with ``asset://`` sentinels.

    Returns a new structure; the caller's document is never mutated.
    """
    if isinstance(node, dict):
        return {key: to_sentinels(value, url_to_name) for key, value in node.items()}
    if isinstance(node, list):
        return [to_sentinels(value, url_to_name) for value in node]
    if isinstance(node, str) and node in url_to_name:
        return f"{ASSET_SCHEME}{url_to_name[node]}"
    return node


def from_sentinels(node: Any, name_to_url: dict[str, str]) -> Any:
    """Resolve ``asset://`` sentinels back to live URLs.

    An unresolvable sentinel is left verbatim rather than blanked. The bundle
    validator rejects those at upload; emitting an empty ``src`` here would
    convert a loud, fixable error into a silently broken image instead.
    """
    if isinstance(node, dict):
        return {key: from_sentinels(value, name_to_url) for key, value in node.items()}
    if isinstance(node, list):
        return [from_sentinels(value, name_to_url) for value in node]
    if isinstance(node, str) and node.startswith(ASSET_SCHEME):
        return name_to_url.get(node[len(ASSET_SCHEME) :], node)
    return node


def collect_sentinels(node: Any) -> set[str]:
    """Every bundle name referenced by an ``asset://`` sentinel in *node*."""
    found: set[str] = set()
    if isinstance(node, dict):
        for value in node.values():
            found |= collect_sentinels(value)
    elif isinstance(node, list):
        for value in node:
            found |= collect_sentinels(value)
    elif isinstance(node, str) and node.startswith(ASSET_SCHEME):
        found.add(node[len(ASSET_SCHEME) :])
    return found


def bundle_names(assets: list[tuple[int, str]]) -> dict[int, str]:
    """Assign each media id a collision-free name to carry in the bundle.

    ``original_filename`` is a label, not a key — two different uploads can
    share one, and a bundle that keyed on it would silently drop a file.
    Sorting by media id keeps the ``~2`` suffixes identical across repeated
    captures, which is what makes the round-trip test meaningful.
    """
    taken: set[str] = set()
    names: dict[int, str] = {}
    for asset_id, original in sorted(assets):
        candidate = original
        if candidate in taken:
            stem = PurePosixPath(original).stem
            suffix = PurePosixPath(original).suffix
            counter = 2
            while candidate in taken:
                candidate = f"{stem}~{counter}{suffix}"
                counter += 1
        taken.add(candidate)
        names[asset_id] = candidate
    return names
