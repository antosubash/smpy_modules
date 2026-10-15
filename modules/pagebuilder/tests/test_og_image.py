"""A blank Social image falls back to the page's first image, as the SEO panel says."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pagebuilder.og_image import first_image, og_image

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


def _image(src: str) -> dict:
    return {"type": "Image", "props": {"id": src, "src": src}}


def test_first_image_takes_document_order() -> None:
    data = {
        "content": [
            {"type": "Heading", "props": {"text": "Hi"}},
            {"type": "Columns", "props": {"left": [_image("/media/nested.png")]}},
            _image("/media/later.png"),
        ],
        "zones": {"x:z": [_image("/media/zone.png")]},
    }
    assert first_image(data) == "/media/nested.png"


def test_first_image_reads_legacy_zones_and_ignores_blank_src() -> None:
    data = {"content": [_image("  ")], "zones": {"x:z": [_image("/media/zone.png")]}}
    assert first_image(data) == "/media/zone.png"


def test_no_image_is_none() -> None:
    assert first_image({"content": [{"type": "Hero", "props": {"image": "/x.png"}}]}) is None
    assert og_image(None, {}, "https://site.example") is None


def test_explicit_wins_and_relative_becomes_absolute() -> None:
    data = {"content": [_image("/media/a.png")]}
    assert og_image("https://cdn.example/b.png", data, "https://s.example") == (
        "https://cdn.example/b.png"
    )
    assert og_image("", data, "https://s.example") == "https://s.example/media/a.png"
    assert og_image("//cdn.example/c.png", data, "https://s.example") == "//cdn.example/c.png"


@pytest.mark.asyncio
async def test_public_page_falls_back_to_its_first_image(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "Gallery",
            "slug": "gallery",
            "draft_data": {"content": [_image("/media/hero.png")], "root": {"props": {}}},
        },
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    assert (await authed_client.post(f"/api/pagebuilder/pages/{page_id}/publish")).status_code == 200

    props = (await authed_client.get("/p/gallery", headers=INERTIA)).json()["props"]

    assert props["og_image"].endswith("/media/hero.png")
    assert props["og_image"].startswith("http")
