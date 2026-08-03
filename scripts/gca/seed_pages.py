"""Seed the Global Canopy Atlas pages into the running demo host.

The content in ``scripts/gca/content/*.json`` is GCA's own page-builder data,
extracted verbatim from IIASA.GeoWiki. Only two things are rewritten here:

* image paths — every photograph is uploaded into the module's own media
  library and the content is rewritten to the returned URL, so the pictures
  on a page are swappable from the editor's image picker rather than being
  baked into a static path;
* root props — the pages are full-bleed and want the GCA design pack, which
  the base config doesn't default to.

Usage (host must already be running and migrated):

    uv run python scripts/gca/seed_pages.py
    uv run python scripts/gca/seed_pages.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

CONTENT_DIR = Path(__file__).parent / "content"
IMAGE_DIR = Path(__file__).resolve().parents[2] / "host" / "static" / "gca" / "images"
DEFAULT_BASE_URL = "http://localhost:8000"

# GCA's own photography, copied from IIASA.GeoWiki's
# frontend/packages/gca/data/gca/images. GeoWiki's seed uploads them into its
# file store the same way this one uploads them into the media library.

GCA_APP_NAME = "Global Canopy Atlas"
# The ink from the "🎨 GCA Design System" Buttons/Links page (SNAG_005) — GCA's
# action colour, not the green.
GCA_PRIMARY_COLOR = "#1a353e"


def upload_images(client: httpx.Client, base_url: str, headers: dict[str, str]) -> dict[str, str]:
    """Upload every GCA photograph into the media library.

    Returns ``{"/gca/images/<name>.jpg": "<media url>"}``. Re-running is safe:
    an already-uploaded name is reused rather than duplicated, so the seed is
    idempotent and page content keeps pointing at the same asset.
    """
    existing = client.get(
        f"{base_url}/api/pagebuilder/uploads",
        params={"limit": 200},
        headers={"Accept": "application/json"},
    ).json()
    by_name = {a["original_filename"]: a["url"] for a in existing.get("items", [])}

    mapping: dict[str, str] = {}
    for path in sorted(IMAGE_DIR.glob("*.jpg")):
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


def seed_branding(client: httpx.Client, base_url: str) -> str | None:
    """Point Settings → Branding at GCA's app name and action colour.

    The design pack owns type, layout and neutrals but deliberately not the
    action colour: ``--pb-accent`` and the solid ``bg-primary-800`` surfaces
    read ``--primary``, which BrandingHead writes from this value. Seeding it
    is therefore what makes the pages render in GCA's ink rather than the
    framework's default teal — and re-picking the colour in the admin UI
    re-themes every GCA page without touching CSS.
    """
    # Branding has its own view layer, so its CSRF cookie is a different one
    # from the page-builder's.
    client.get(f"{base_url}/branding")
    token = client.cookies.get("branding_csrf")
    response = client.put(
        f"{base_url}/api/branding/",
        json={"app_name": GCA_APP_NAME, "primary_color": GCA_PRIMARY_COLOR},
        headers={"X-CSRF-Token": token} if token else {},
    )
    if response.status_code >= 400:
        print(f"Branding: FAILED ({response.status_code}) {response.text[:120]}")
        return None
    return response.json().get("primary_color")


def rewrite_asset_paths(node: Any, uploads: dict[str, str]) -> Any:
    """Repoint image paths at their media-library URLs.

    Photographs resolve through *uploads*. The brand and partner marks stay on
    the static mount: they are SVG, and the media library deliberately rejects
    SVG because it can carry script and is served same-origin. An author can
    still swap any of them for an uploaded raster via the picker.
    """
    if isinstance(node, dict):
        return {k: rewrite_asset_paths(v, uploads) for k, v in node.items()}
    if isinstance(node, list):
        return [rewrite_asset_paths(v, uploads) for v in node]
    if isinstance(node, str):
        if node in uploads:
            return uploads[node]
        # In-site links like "/gca/contact" stay as they are so they keep
        # pointing at page routes rather than at files.
        if node.startswith("/gca/partners/"):
            return f"/static{node}"
    return node


def login(client: httpx.Client, base_url: str, email: str, password: str) -> None:
    # The auth endpoint takes an OAuth2 password form, not JSON, and calls the
    # identity field "username" even though it holds an email address.
    response = client.post(
        f"{base_url}/api/users/auth/login",
        data={"username": email, "password": password},
    )
    if response.status_code not in (200, 204):
        raise SystemExit(f"login failed ({response.status_code}): {response.text[:200]}")


def csrf_headers(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("pagebuilder_csrf")
    return {"X-CSRF-Token": token} if token else {}


def seed(base_url: str, email: str, password: str, publish: bool) -> int:
    manifest = json.loads((CONTENT_DIR / "_manifest.json").read_text())

    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        login(client, base_url, email, password)
        # The CSRF cookie is issued by the admin view layer, not the API.
        client.get(f"{base_url}/pagebuilder/")
        headers = csrf_headers(client)

        uploads = upload_images(client, base_url, headers)
        print(f"Media library: {len(uploads)} image(s) available to pages.")

        color = seed_branding(client, base_url)
        if color:
            print(f"Branding: {GCA_APP_NAME}, action colour {color}.")
        print()

        existing = client.get(
            f"{base_url}/api/pagebuilder/pages", headers={"Accept": "application/json"}
        ).json()
        by_slug = {p["slug"]: p["id"] for p in existing.get("items", [])}

        seeded = 0
        for entry in manifest:
            slug, title = entry["slug"], entry["title"]
            data = json.loads((CONTENT_DIR / f"{slug}.json").read_text())
            data = rewrite_asset_paths(data, uploads)
            # These pages are composed of full-bleed sections and expect the
            # GCA pack; the base config defaults to neither.
            data.setdefault("root", {}).setdefault("props", {})
            data["root"]["props"].update(
                {"title": title, "width": "full", "designPack": "gca"}
            )

            payload = {"title": title, "slug": slug, "draft_data": data}
            if slug in by_slug:
                page_id = by_slug[slug]
                response = client.put(
                    f"{base_url}/api/pagebuilder/pages/{page_id}",
                    json=payload,
                    headers=headers,
                )
            else:
                response = client.post(
                    f"{base_url}/api/pagebuilder/pages", json=payload, headers=headers
                )
                page_id = response.json().get("id") if response.status_code < 400 else None

            if response.status_code >= 400:
                print(f"  {slug}: FAILED ({response.status_code}) {response.text[:120]}")
                continue

            if publish and page_id is not None:
                pub = client.post(
                    f"{base_url}/api/pagebuilder/pages/{page_id}/publish",
                    json={"note": "GCA seed"},
                    headers=headers,
                )
                if pub.status_code >= 400:
                    print(f"  {slug}: saved but publish failed ({pub.status_code})")
                    continue

            blocks = len(data.get("content", []))
            print(f"  {slug}: {blocks} blocks -> /p/{slug}")
            seeded += 1

    print(f"\nSeeded {seeded}/{len(manifest)} pages.")
    print(
        "Every photograph is served from the media library, so any of them can "
        "be swapped from the editor's image picker."
    )
    print(
        "Brand and partner marks stay on /static: they are SVG, which the "
        "media library rejects because it can carry script."
    )
    print(
        "The action colour comes from Settings → Branding, so re-picking it "
        "there re-themes every GCA page."
    )
    return 0 if seeded == len(manifest) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="changeme1")
    parser.add_argument(
        "--no-publish", action="store_true", help="seed as drafts instead of publishing"
    )
    args = parser.parse_args()
    return seed(args.base_url, args.email, args.password, publish=not args.no_publish)


if __name__ == "__main__":
    sys.exit(main())
