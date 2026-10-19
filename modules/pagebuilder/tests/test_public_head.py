"""HEAD shares public GET handlers, including locale and redirect handling."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio
API = "/api/pagebuilder/pages"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
# A visitor, on the admin-authed app: only an anonymous copy has an ETag (#94).
ANON = {"X-Test-Anonymous": "1"}


async def _publish(client: AsyncClient, locale: str) -> int:
    created = await client.post(
        API,
        json={
            "title": "Hello",
            "slug": "hello",
            "locale": locale,
            "draft_data": {"content": []},
        },
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    published = await client.post(f"{API}/{page_id}/publish")
    assert published.status_code == 200
    return page_id


@pytest.mark.parametrize("locale,prefix", [("en", "/p"), ("de", "/de/p")])
@pytest.mark.parametrize("headers", [ANON, {**INERTIA, **ANON}])
async def test_head_published_and_conditional(
    bilingual_client: AsyncClient, locale: str, prefix: str, headers: dict
) -> None:
    await _publish(bilingual_client, locale)
    url = f"{prefix}/hello"
    get = await bilingual_client.get(url, headers=headers)
    head = await bilingual_client.head(url, headers=headers)
    assert head.status_code == get.status_code == 200
    assert head.content == b""
    for name in (
        "etag",
        "cache-control",
        "vary",
        "content-language",
        "content-security-policy",
        "content-type",
        "content-length",
    ):
        assert head.headers[name] == get.headers[name]
    conditional = {**headers, "If-None-Match": get.headers["etag"]}
    get = await bilingual_client.get(url, headers=conditional)
    head = await bilingual_client.head(url, headers=conditional)
    assert head.status_code == get.status_code == 304
    assert head.headers == get.headers
    assert head.content == b""


@pytest.mark.parametrize("prefix", ["/p", "/de/p"])
async def test_head_missing(bilingual_client: AsyncClient, prefix: str) -> None:
    get = await bilingual_client.get(f"{prefix}/missing")
    head = await bilingual_client.head(f"{prefix}/missing")
    assert head.status_code == get.status_code == 404
    assert head.content == b""
    assert head.headers == get.headers


@pytest.mark.parametrize("locale,prefix", [("en", "/p"), ("de", "/de/p")])
async def test_head_renamed(bilingual_client: AsyncClient, locale: str, prefix: str) -> None:
    page_id = await _publish(bilingual_client, locale)
    renamed = await bilingual_client.put(f"{API}/{page_id}", json={"slug": "renamed"})
    assert renamed.status_code == 200
    published = await bilingual_client.post(f"{API}/{page_id}/publish")
    assert published.status_code == 200
    get = await bilingual_client.get(f"{prefix}/hello", follow_redirects=False)
    head = await bilingual_client.head(f"{prefix}/hello", follow_redirects=False)
    assert head.status_code == get.status_code == 301
    assert head.headers["location"] == get.headers["location"] == f"{prefix}/renamed"
    assert head.headers == get.headers
    assert head.content == b""


async def test_head_default_locale_alias(bilingual_client: AsyncClient) -> None:
    get = await bilingual_client.get("/en/p/hello", follow_redirects=False)
    head = await bilingual_client.head("/en/p/hello", follow_redirects=False)
    assert head.status_code == get.status_code == 301
    assert head.headers["location"] == get.headers["location"] == "/p/hello"
    assert head.content == b""


@pytest.mark.parametrize("url", ["/sitemap.xml", "/robots.txt"])
async def test_head_crawler_routes(bilingual_client: AsyncClient, url: str) -> None:
    get = await bilingual_client.get(url)
    head = await bilingual_client.head(url)
    assert head.status_code == get.status_code == 200
    assert head.headers == get.headers
    assert head.content == b""
