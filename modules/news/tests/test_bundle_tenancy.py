"""The news section works inside the tenant pagebuilder bound, and only there (#80).

News never resolves a tenant for a restore — ``news.tenancy`` is not
consulted. It takes ``ctx.tenant_id``, checks it is still the bound one, and
the framework's tenant filter keeps every statement (the redirect rebuild's
bulk deletes included) inside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bundle_app import add, bundle_host, news_files, restore, session, take
from news.integrations.bundle import NewsBundleSection
from news.models import (
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
    NewsTagRedirect,
)
from pagebuilder.contracts.bundle import CaptureContext, TenantMismatchError
from simple_module_db import tenant_context
from sqlmodel import select

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]

_MODELS = (NewsArticle, NewsArticleTag, NewsArticleRedirect, NewsCategory, NewsTag, NewsTagRedirect)


async def _seed(client, tenant: str, title: str) -> None:
    with tenant_context(tenant):
        [row] = await add(client, NewsArticle(slug="launch", title=title, translation_group="g1"))
        [tag] = await add(client, NewsTag(name="Python", slug="python"))
        await add(
            client,
            NewsCategory(name="Updates", slug="updates"),
            NewsArticleTag(article_id=row.id, tag_id=tag.id),
            NewsArticleRedirect(from_slug="old", locale="en", article_id=row.id),
            NewsTagRedirect(from_slug="py", tag_id=tag.id),
        )


async def _dump(client, tenant: str) -> list[dict]:
    """Every news row of *tenant*, as plain dicts."""
    with tenant_context(tenant):
        async with session(client) as db:
            out = []
            for model in _MODELS:
                rows = (await db.execute(select(model))).scalars().all()
                out += [{"table": model.__tablename__, **r.model_dump()} for r in rows]
    return sorted(out, key=repr)


async def test_a_restore_in_one_tenant_never_touches_another(tmp_path):
    acme, globex = {"x-tenant": "acme"}, {"x-tenant": "globex"}
    async with bundle_host(tmp_path, multi=True) as client:
        await _seed(client, "acme", "Acme launch")
        await _seed(client, "globex", "Globex launch")

        snapshot = await take(client, acme)
        files = news_files(client, snapshot["id"])
        assert files["articles/launch.json"]["title"] == "Acme launch"
        assert snapshot["manifest"]["contents"][-1]["counts"]["articles"] == 1

        with tenant_context("globex"):
            async with session(client) as db:
                row = (await db.execute(select(NewsArticle))).scalar_one()
                row.title = "Globex edited"
                await db.commit()
        with tenant_context("acme"):
            async with session(client) as db:
                row = (await db.execute(select(NewsArticle))).scalar_one()
                row.title = "Acme edited"
                await db.commit()
        globex_before = await _dump(client, "globex")

        await restore(client, snapshot["id"], acme)

        assert await _dump(client, "globex") == globex_before
        acme_rows = await _dump(client, "acme")
        [acme_article] = [r for r in acme_rows if r["table"] == "news_articles"]
        assert acme_article["title"] == "Acme launch"
        assert {r["table"] for r in acme_rows} == {m.__tablename__ for m in _MODELS}
        assert (await take(client, globex))["manifest"]["contents"][-1]["counts"]["articles"] == 1


async def test_a_section_called_outside_its_tenant_fails_closed(tmp_path: Path):
    async with bundle_host(tmp_path, multi=True) as client, session(client) as db:
        ctx = CaptureContext(
            db=db, tenant_id="acme", dir=tmp_path / "news", to_portable=lambda node: node
        )
        with tenant_context("globex"), pytest.raises(TenantMismatchError):
            await NewsBundleSection().capture(ctx)
        with pytest.raises(TenantMismatchError):
            await NewsBundleSection().capture(ctx)  # nothing bound at all
