"""Seed the Global Canopy Atlas site into a running host.

The content in ``seed/content/*.json`` is GCA's own page-builder data,
extracted verbatim from IIASA.GeoWiki. Two things are rewritten on the way in:

* asset paths — every photograph is uploaded into pagebuilder's media library
  and the content repointed at the returned URL, so the pictures on a page are
  swappable from the editor's image picker rather than baked into a static
  path. The SVG brand and partner marks resolve to this module's static mount
  instead, because the media library rejects SVG;
* root props — the pages are full-bleed, which the base config doesn't default
  to.

Usage (the host must already be running and migrated):

    uv run python -m canopy_atlas.seed
    uv run python -m canopy_atlas.seed --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys

import httpx

from canopy_atlas.seed.pages import (
    APP_NAME,
    csrf_headers,
    login,
    seed_branding,
    seed_layout,
    seed_pages,
)
from canopy_atlas.seed.uploads import upload_images

DEFAULT_BASE_URL = "http://localhost:8000"


def run(base_url: str, email: str, password: str, *, publish: bool) -> int:
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        login(client, base_url, email, password)
        # The CSRF cookie is issued by the admin view layer, not the API.
        client.get(f"{base_url}/pagebuilder/")
        headers = csrf_headers(client)

        uploads = upload_images(client, base_url, headers)
        print(f"Media library: {len(uploads)} image(s) available to pages.")

        branding = seed_branding(client, base_url)
        if branding:
            print(
                f"Branding: {APP_NAME}, action colour {branding['primary_color']}, "
                f"design pack {branding['design_pack']!r}."
            )

        chrome = seed_layout(client, base_url, headers, uploads)
        if chrome:
            print(f"Site layout: {chrome} header/footer block(s).")
        print()

        seeded, total = seed_pages(client, base_url, headers, uploads, publish=publish)

    print(f"\nSeeded {seeded}/{total} pages.")
    print(
        "Every photograph is served from the media library, so any of them can "
        "be swapped from the editor's image picker."
    )
    print(
        "Brand and partner marks stay on the module's static mount: they are "
        "SVG, which the media library rejects because it can carry script."
    )
    print(
        "The look comes from Settings → Branding — action colour and design "
        "pack — so re-picking either there re-themes the whole site."
    )
    return 0 if seeded == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="changeme1")
    parser.add_argument(
        "--no-publish", action="store_true", help="seed as drafts instead of publishing"
    )
    args = parser.parse_args()
    return run(args.base_url, args.email, args.password, publish=not args.no_publish)


if __name__ == "__main__":
    sys.exit(main())
