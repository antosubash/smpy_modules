"""Media picking is a server-decided convenience; stored images stay URLs."""

import pytest
from news.contracts.schemas import ArticleBodyUpdate, ArticleUpdate
from news.core.safe_url import image_or_none
from news.integrations import pagebuilder
from news.web.endpoints import views
from starlette.requests import Request


class Inertia:
    async def render(self, component, props):
        return props


@pytest.mark.parametrize("screen", ["article_editor", "article_body"])
@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize(
    "permission", [None, "pagebuilder.edit", "pagebuilder.publish", "pagebuilder.approve", "*"]
)
async def test_picker_capability_requires_pagebuilder_and_its_read_permission(
    monkeypatch, screen, installed, permission
):
    monkeypatch.setattr(pagebuilder, "available", lambda: installed)
    held = {"news.edit"}
    if permission:
        held.add(permission)
    request = Request({"type": "http", "state": {"resolved_permissions": held}})
    props = await getattr(views, screen)(article_id=1, inertia=Inertia(), request=request)
    assert props["media_picker"] is (installed and permission is not None)


@pytest.mark.parametrize("url", ["/media/default/cover.webp", "https://cdn.example/cover.webp"])
def test_picked_urls_pass_existing_validation_and_public_link_safety(url):
    assert ArticleUpdate(og_image=url).og_image == url
    assert image_or_none(url) == url
    body = {"content": [{"type": "Image", "props": {"url": url}}]}
    assert ArticleBodyUpdate(draft_data=body).draft_data == body
