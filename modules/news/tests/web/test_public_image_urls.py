"""Share images use the canonical origin without changing stored media paths."""

from __future__ import annotations

from html import escape

import pytest
from news.core import settings as news_settings
from news.core.settings import NewsSettings
from news.models import NewsArticle
from news.web.endpoints.public import _article, _urls

from tests.support.factories import make_article

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("base", "reference", "expected"),
    [
        (
            "",
            "/media/pagebuilder/default/cover.webp",
            "http://test/media/pagebuilder/default/cover.webp",
        ),
        (
            "https://news.example/",
            "/media/pagebuilder/default/cover.webp",
            "https://news.example/media/pagebuilder/default/cover.webp",
        ),
        ("", "https://cdn.example/cover.webp", "https://cdn.example/cover.webp"),
        (
            "https://news.example/",
            "https://cdn.example/cover.webp",
            "https://cdn.example/cover.webp",
        ),
        ("https://news.example", "//other.example/cover.webp", None),
        ("https://news.example", "/\\other.example/cover.webp", None),
        ("https://news.example", "javascript:alert(1)", None),
        ("https://news.example", "data:image/png;base64,AA==", None),
        ("https://news.example", "mailto:editor@example.com", None),
        ("https://news.example", "", None),
        ("https://news.example", None, None),
        (
            "https://news.example",
            "/media/cover.webp?width=800&fit=cover#hero",
            "https://news.example/media/cover.webp?width=800&fit=cover#hero",
        ),
        (
            "https://news.example",
            "/media/caf%C3%A9.webp",
            "https://news.example/media/caf%C3%A9.webp",
        ),
        ("https://news.example", "/media/café.webp", "https://news.example/media/café.webp"),
    ],
)
async def test_both_heads_receive_the_same_safe_absolute_image(
    anon_client, base, reference, expected
) -> None:
    news_settings.use(NewsSettings(public_base_url=base))
    async with anon_client.db_state.session_factory() as db:
        article = await make_article(
            db,
            slug="cover",
            og_image=reference,
        )
        # A syndicated canonical is not the origin that hosts our media.
        article.canonical_url = "https://syndicated.example/story"
        db.add(article)
        await db.commit()
        article_id = article.id

    response = await anon_client.get("/news/cover")
    assert response.status_code == 200
    head = response.text.split("</head>", 1)[0]
    if expected is None:
        assert 'property="og:image"' not in head
        assert 'name="twitter:image"' not in head
    else:
        assert f'<meta property="og:image" content="{escape(expected)}">' in head
        assert f'<meta name="twitter:image" content="{escape(expected)}">' in head

    page = await anon_client.get(
        "/news/cover", headers={"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    )
    assert page.status_code == 200
    assert page.json()["props"]["og_image"] == expected

    async with anon_client.db_state.session_factory() as db:
        stored = await db.get(NewsArticle, article_id)
        assert stored is not None
        assert stored.og_image == reference


@pytest.mark.parametrize("configured", [True, False])
async def test_changed_image_origin_invalidates_the_article_etag(anon_client, configured) -> None:
    news_settings.use(NewsSettings(public_base_url="https://old.example" if configured else ""))
    async with anon_client.db_state.session_factory() as db:
        article = await make_article(
            db,
            slug="cover",
            og_image="/media/cover.webp",
        )
        article.canonical_url = "https://syndicated.example/story"
        db.add(article)
        await db.commit()

    first = await anon_client.get("/news/cover" if configured else "https://old.example/news/cover")
    assert first.status_code == 200
    assert 'content="https://old.example/media/cover.webp"' in first.text

    news_settings.use(NewsSettings(public_base_url="https://new.example" if configured else ""))
    changed = await anon_client.get(
        "/news/cover" if configured else "https://new.example/news/cover",
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert changed.status_code == 200
    assert 'content="https://new.example/media/cover.webp"' in changed.text
    assert changed.headers["etag"] != first.headers["etag"]
    unchanged = await anon_client.get(
        "/news/cover" if configured else "https://new.example/news/cover",
        headers={"If-None-Match": changed.headers["etag"]},
    )
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    for header in ("etag", "cache-control", "content-language"):
        assert unchanged.headers[header] == changed.headers[header]
    # The HTML session middleware may append a redundant Cookie entry.
    assert {field.strip().lower() for field in unchanged.headers["vary"].split(",")} == {
        field.strip().lower() for field in changed.headers["vary"].split(",")
    }


async def test_article_resolves_one_origin_for_its_validator_and_urls(
    bilingual_public_client, monkeypatch
) -> None:
    anon_client = bilingual_public_client
    async with anon_client.db_state.session_factory() as db:
        await make_article(
            db, slug="cover", og_image="/media/cover.webp", translation_group="cover"
        )
        await make_article(db, slug="cover-de", locale="de", translation_group="cover")

    origins = []
    resolve = _urls.public_base_url

    def track_origin(request, settings):
        base = resolve(request, settings)
        origins.append(base)
        return base

    monkeypatch.setattr(_article, "public_base_url", track_origin)
    monkeypatch.setattr(_urls, "public_base_url", track_origin)
    response = await anon_client.get("/news/cover")
    assert response.status_code == 200
    assert '<link rel="canonical" href="http://test/news/cover">' in response.text
    assert '<meta property="og:image" content="http://test/media/cover.webp">' in response.text
    assert 'hreflang="de" href="http://test/de/news/cover-de"' in response.text
    assert origins == ["http://test"]


@pytest.mark.parametrize("header", ["Host", "X-Forwarded-Host"])
async def test_configured_origin_ignores_untrusted_hosts_in_urls_and_etag(
    anon_client, header
) -> None:
    news_settings.use(NewsSettings(public_base_url="https://news.example/"))
    async with anon_client.db_state.session_factory() as db:
        await make_article(db, slug="cover", og_image="/media/cover.webp")

    first = await anon_client.get("/news/cover")
    other = await anon_client.get("/news/cover", headers={header: "attacker.example"})
    assert first.status_code == other.status_code == 200
    assert other.headers["etag"] == first.headers["etag"]
    assert '<link rel="canonical" href="https://news.example/news/cover">' in other.text
    assert (
        '<meta property="og:image" content="https://news.example/media/cover.webp">' in other.text
    )
    assert "attacker.example" not in other.text
