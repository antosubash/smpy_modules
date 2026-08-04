"""Media uploads and asset-path rewriting for the GCA seed."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import httpx

from canopy_atlas.module import STATIC_MOUNT

IMAGE_DIR = files("canopy_atlas") / "static" / "gca" / "images"

# GCA's own photography, copied from IIASA.GeoWiki's
# frontend/packages/gca/data/gca/images. GeoWiki's seed uploads them into its
# file store the same way this one uploads them into the media library.

# Brand lockups used by the header and footer. Like the partner marks these are
# SVG, so they stay on the static mount rather than the media library.
STATIC_LOGOS = frozenset({"/gca/logo-main.svg", "/gca/logo-reversed.svg"})


def upload_images(
    client: httpx.Client, base_url: str, headers: dict[str, str]
) -> dict[str, str]:
    """Upload every GCA photograph into pagebuilder's media library.

    Returns ``{"/gca/images/<name>.jpg": "<media url>"}``. Re-running is safe:
    an already-uploaded name is reused rather than duplicated, so the seed is
    idempotent and page content keeps pointing at the same asset.
    """
    existing = client.get(
        f"{base_url}/api/pagebuilder/uploads",
        params={"limit": 200},
        headers={"Accept": "application/json"},
    ).json()
    by_name = {asset["original_filename"]: asset["url"] for asset in existing.get("items", [])}

    mapping: dict[str, str] = {}
    for path in sorted(IMAGE_DIR.iterdir()):
        if path.suffix != ".jpg":
            continue
        if path.name in by_name:
            mapping[f"/gca/images/{path.name}"] = by_name[path.name]
            continue
        response = client.post(
            f"{base_url}/api/pagebuilder/uploads",
            files={"file": (path.name, path.read_bytes(), "image/jpeg")},
            data={"folder": "gca"},
            headers=headers,
        )
        if response.status_code >= 400:
            print(f"  upload {path.name}: FAILED ({response.status_code})")
            continue
        mapping[f"/gca/images/{path.name}"] = response.json()["url"]
    return mapping


def rewrite_asset_paths(node: Any, uploads: dict[str, str]) -> Any:
    """Repoint the content's asset paths at where they are actually served.

    Photographs resolve through *uploads* — every one is in the media library,
    so an editor can swap it from the image picker.

    The brand and partner marks resolve to this module's static mount instead:
    they are SVG, and the media library deliberately rejects SVG because it can
    carry script and is served same-origin. An author can still replace any of
    them with an uploaded raster through the picker.
    """
    if isinstance(node, dict):
        return {key: rewrite_asset_paths(value, uploads) for key, value in node.items()}
    if isinstance(node, list):
        return [rewrite_asset_paths(value, uploads) for value in node]
    if isinstance(node, str):
        if node in uploads:
            return uploads[node]
        # In-site links like "/gca/contact" stay as they are so they keep
        # pointing at page routes rather than at files. Only the marks below
        # are files.
        if node.startswith("/gca/partners/") or node in STATIC_LOGOS:
            return f"{STATIC_MOUNT}{node}"
    return node
