"""Seed the Global Canopy Atlas pages into the running demo host.

The content in ``scripts/gca/content/*.json`` is GCA's own page-builder data,
extracted verbatim from IIASA.GeoWiki. Only two things are rewritten here:

* asset paths — GeoWiki serves them from its frontend `public/` dir at
  ``/gca/...``; this host serves ``host/static`` at ``/static``;
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
DEFAULT_BASE_URL = "http://localhost:8000"

# Photographs GCA's content references that are NOT in the GeoWiki repo — its
# seed uploads them from a local directory. We ship marked placeholders at the
# same names so the layout is honest about what's missing.
PLACEHOLDER_PHOTOS = {
    "atlas-map",
    "biodiversity",
    "canopy-aerial",
    "canopy-up",
    "collaboration",
    "forest-aerial-river",
    "governance-diagram",
    "hero-lidar",
}


def rewrite_asset_paths(node: Any) -> Any:
    """Point GeoWiki's ``/gca/...`` asset paths at this host's static mount."""
    if isinstance(node, dict):
        return {k: rewrite_asset_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [rewrite_asset_paths(v) for v in node]
    # Only assets move; in-site links like "/gca/contact" stay as they are so
    # they keep pointing at page routes rather than at files.
    if isinstance(node, str) and node.startswith(("/gca/images/", "/gca/partners/")):
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

        existing = client.get(
            f"{base_url}/api/pagebuilder/pages", headers={"Accept": "application/json"}
        ).json()
        by_slug = {p["slug"]: p["id"] for p in existing.get("items", [])}

        seeded = 0
        for entry in manifest:
            slug, title = entry["slug"], entry["title"]
            data = json.loads((CONTENT_DIR / f"{slug}.json").read_text())
            data = rewrite_asset_paths(data)
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
        "Placeholder imagery stands in for photographs GeoWiki seeds from a "
        "local directory that isn't in its repo:\n  "
        + ", ".join(sorted(PLACEHOLDER_PHOTOS))
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
