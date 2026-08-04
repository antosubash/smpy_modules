"""Branding, site layout and page seeding for the GCA site."""

from __future__ import annotations

import json
from importlib.resources import files

import httpx

from canopy_atlas.seed.articles import use_live_feed
from canopy_atlas.seed.uploads import rewrite_asset_paths

CONTENT_DIR = files("canopy_atlas") / "seed" / "content"

APP_NAME = "Global Canopy Atlas"
# The ink from the "🎨 GCA Design System" Buttons/Links page (SNAG_005) — GCA's
# action colour, not the green.
PRIMARY_COLOR = "#1a353e"
DESIGN_PACK = "gca"


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


def seed_branding(client: httpx.Client, base_url: str) -> dict | None:
    """Point Settings → Branding at GCA's name, action colour and design pack.

    The pack owns type, layout and neutrals but deliberately not the action
    colour: ``--pb-accent`` and the solid ``bg-primary-800`` surfaces read
    ``--primary``, which BrandingHead writes from this value. Seeding both is
    what makes the pages render as GCA rather than in the framework defaults —
    and re-picking either in the admin re-themes the site without touching CSS.
    """
    # Branding has its own view layer, so its CSRF cookie is a different one
    # from the page-builder's.
    client.get(f"{base_url}/branding/")
    token = client.cookies.get("branding_csrf")
    response = client.put(
        f"{base_url}/api/branding/",
        json={
            "app_name": APP_NAME,
            "primary_color": PRIMARY_COLOR,
            "design_pack": DESIGN_PACK,
        },
        headers={"X-CSRF-Token": token} if token else {},
    )
    if response.status_code >= 400:
        print(f"Branding: FAILED ({response.status_code}) {response.text[:160]}")
        return None
    return response.json()


def seed_layout(
    client: httpx.Client, base_url: str, headers: dict[str, str], uploads: dict[str, str]
) -> int:
    """Publish GCA's header and footer into the site-wide layout.

    The layout is one record shared by every page, which is what a header and
    footer are — so they live there rather than being repeated at the top and
    bottom of twelve pages.
    """
    layout = json.loads((CONTENT_DIR / "_layout.json").read_text())
    response = client.put(
        f"{base_url}/api/pagebuilder/layout",
        json={
            "header_data": rewrite_asset_paths(layout["header"], uploads),
            "footer_data": rewrite_asset_paths(layout["footer"], uploads),
            "note": "GCA seed",
        },
        headers=headers,
    )
    if response.status_code >= 400:
        print(f"Layout: FAILED ({response.status_code}) {response.text[:160]}")
        return 0
    return len(layout["header"]["content"]) + len(layout["footer"]["content"])


def _existing_pages(client: httpx.Client, base_url: str) -> dict[str, int]:
    body = client.get(
        f"{base_url}/api/pagebuilder/pages", headers={"Accept": "application/json"}
    ).json()
    return {page["slug"]: page["id"] for page in body.get("items", [])}


def seed_pages(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    uploads: dict[str, str],
    *,
    publish: bool,
    live_feed: bool = False,
) -> tuple[int, int]:
    """Create or update every page in the manifest. Returns (seeded, total).

    With *live_feed*, the news strips become NewsFeed blocks reading the news
    API instead of the hand-authored cards baked into the content.
    """
    manifest = json.loads((CONTENT_DIR / "_manifest.json").read_text())
    by_slug = _existing_pages(client, base_url)

    seeded = 0
    for entry in manifest:
        slug, title = entry["slug"], entry["title"]
        data = json.loads((CONTENT_DIR / f"{slug}.json").read_text())
        data = rewrite_asset_paths(data, uploads)
        if live_feed:
            data = use_live_feed(data)
        # These pages are composed of full-bleed sections; the base config
        # defaults to a contained column. The design pack is *not* set here —
        # it is a site-wide branding setting, not a page property.
        data.setdefault("root", {}).setdefault("props", {})
        data["root"]["props"].update({"title": title, "width": "full"})

        payload = {"title": title, "slug": slug, "draft_data": data}
        if slug in by_slug:
            page_id = by_slug[slug]
            response = client.put(
                f"{base_url}/api/pagebuilder/pages/{page_id}", json=payload, headers=headers
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
            published = client.post(
                f"{base_url}/api/pagebuilder/pages/{page_id}/publish",
                json={"note": "GCA seed"},
                headers=headers,
            )
            if published.status_code >= 400:
                print(f"  {slug}: saved but publish failed ({published.status_code})")
                continue

        print(f"  {slug}: {len(data.get('content', []))} blocks -> /p/{slug}")
        seeded += 1

    return seeded, len(manifest)
