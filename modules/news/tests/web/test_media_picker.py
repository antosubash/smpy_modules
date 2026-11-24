"""Media picking is a server-decided convenience; stored images stay URLs."""

import pytest
from fastapi import FastAPI
from news.contracts.schemas import ArticleBodyUpdate, ArticleUpdate
from news.core.safe_url import image_or_none
from news.integrations import pagebuilder
from news.web.endpoints import views
from starlette.requests import Request


def request_with_permissions(held, *, mounted=True):
    app = FastAPI()
    if mounted:
        app.state.pagebuilder = object()
    return Request(
        {
            "type": "http",
            "app": app,
            "scheme": "https",
            "server": ("editor.internal", 443),
            "path": "/",
            "headers": [],
            "state": {"resolved_permissions": held},
        }
    )


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
    request = request_with_permissions(held)
    props = await getattr(views, screen)(article_id=1, inertia=Inertia(), request=request)
    assert props["media_picker"] is (installed and permission is not None)


@pytest.mark.parametrize("url", ["/media/default/cover.webp", "https://cdn.example/cover.webp"])
def test_picked_urls_pass_existing_validation_and_public_link_safety(url):
    assert ArticleUpdate(og_image=url).og_image == url
    assert image_or_none(url) == url
    body = {"content": [{"type": "Image", "props": {"url": url}}]}
    assert ArticleBodyUpdate(draft_data=body).draft_data == body


@pytest.mark.parametrize("screen", ["article_editor", "article_body"])
async def test_installed_but_unmounted_pagebuilder_has_no_picker(monkeypatch, screen):
    monkeypatch.setattr(pagebuilder, "available", lambda: True)
    request = request_with_permissions({"news.edit", "pagebuilder.edit"}, mounted=False)
    props = await getattr(views, screen)(article_id=1, inertia=Inertia(), request=request)
    assert props["media_picker"] is False
