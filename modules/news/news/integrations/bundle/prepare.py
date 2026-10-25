"""Reading a ``news/`` section and matching it against the live rows (#80).

One computation for the plan and the apply, so the screen an approver reads
and the write that follows cannot disagree about which row a document lands
on — the reason pagebuilder's own plan and apply share ``match_by_identity``,
which this calls too. Run afresh at staging and again at approval, never
trusted from the staged plan: articles move in between.

Everything that cannot land is raised here, before anything is written, as
``ctx.conflict`` (409): an address another article now holds, or a category or
tag slug held by a live one the bundle does not carry. Renaming either out of
the way would silently change something nobody asked about.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pagebuilder.contracts.bundle import IdentityMatch, RestoreContext, match_by_identity
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.integrations.bundle.documents import (
    ARTICLES_DIR,
    CATEGORIES_NAME,
    MEDIA_FIELDS,
    REDIRECTS_NAME,
    TAG_REDIRECTS_NAME,
    TAGS_NAME,
    ArticleKey,
    article_doc,
    comparable,
    doc_key,
    normalise_locale,
)
from news.models import NewsArticle, NewsArticleTag, NewsCategory, NewsTag


@dataclass
class Prepared:
    articles: dict[ArticleKey, dict[str, Any]]
    """Bundle documents by ``(locale, slug)``, media URLs already resolved."""
    match: IdentityMatch[NewsArticle]
    categories: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    redirects: list[dict[str, Any]]
    tag_redirects: list[dict[str, Any]]
    live_categories: dict[str, NewsCategory]
    live_tags: dict[str, NewsTag]
    live_links: dict[int, list[str]] = field(default_factory=dict)
    """Tag names of every matched article, as they are now."""

    def article_targets(self) -> set[ArticleKey]:
        """Every live ``(locale, slug)`` once the restore lands: what a redirect may name."""
        kept = {(r.locale, r.slug) for r in self.match.untouched if r.deleted_at is None}
        return set(self.match.rows) | set(self.match.creates) | kept

    def tag_slugs(self) -> dict[str, str]:
        """Tag slug -> name, once the restore lands."""
        bundled = {t["name"]: t["slug"] for t in self.tags}
        live = {t.slug: name for name, t in self.live_tags.items() if name not in bundled}
        return live | {slug: name for name, slug in bundled.items()}

    def dropped_redirects(self) -> list[dict[str, Any]]:
        """Bundle article redirects whose target will not exist."""
        targets = self.article_targets()
        return [r for r in self.redirects if (r["locale"], r["to_slug"]) not in targets]

    def changed(self, key: ArticleKey) -> bool:
        """Whether restoring *key* writes anything onto its matched row.

        Only the keys the document carries are compared, as only those are
        written; a row found by address keeps its own group, so the bundle's is
        not compared either (``IdentityMatch.writable``).
        """
        row = self.match.rows[key]
        if row.deleted_at is not None or row.slug != key[1]:
            return True
        live = comparable(article_doc(row, self.live_links.get(row.id or 0, [])))
        want = comparable(self.match.writable(key, self.articles[key]))
        if not want.get("translation_group"):
            want.pop("translation_group", None)
        if "tags" in want:
            want["tags"] = sorted(set(want["tags"]))
        return any(live.get(k) != v for k, v in want.items() if k not in ("locale", "slug"))


def _read(ctx: RestoreContext) -> dict[str, Any]:
    directory = ctx.dir / ARTICLES_DIR
    names = sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
    return {
        "articles": [ctx.read_json(f"{ARTICLES_DIR}/{n}") for n in names if n.endswith(".json")],
        **{
            name: ctx.read_json(name, [])
            for name in (CATEGORIES_NAME, TAGS_NAME, REDIRECTS_NAME, TAG_REDIRECTS_NAME)
        },
    }


def _resolved(ctx: RestoreContext, doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out["locale"] = normalise_locale(doc["locale"])
    for name in MEDIA_FIELDS:
        if name in out:
            out[name] = ctx.from_portable(out[name])
    return out


def _check_slugs(
    ctx: RestoreContext, noun: str, bundled: list[dict[str, Any]], live: list[Any]
) -> None:
    """A bundled slug held by a live row the bundle does not carry is a conflict."""
    names = {entry["name"] for entry in bundled}
    by_slug = {row.slug: row for row in live}
    for entry in bundled:
        holder = by_slug.get(entry["slug"])
        if holder is not None and holder.name != entry["name"] and holder.name not in names:
            raise ctx.conflict(
                f"the {noun} slug {entry['slug']!r} now belongs to {holder.name!r}, not "
                f"{entry['name']!r} — rename that {noun} first"
            )


async def _links(db: AsyncSession, ids: list[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    result = await db.execute(
        select(NewsArticleTag.article_id, NewsTag.name)
        .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
        .where(NewsArticleTag.article_id.in_(ids))  # ty: ignore[unresolved-attribute]
    )
    links: dict[int, list[str]] = defaultdict(list)
    for article_id, name in result.all():
        links[article_id].append(name)
    return links


async def prepare(ctx: RestoreContext) -> Prepared:
    """The section as it would land on this tenant right now. Writes nothing."""
    ctx.check_tenant()
    raw = await asyncio.to_thread(_read, ctx)
    articles = {doc_key(doc): _resolved(ctx, doc) for doc in raw["articles"]}
    # Every article of the tenant, trashed included: a trashed row still holds
    # its slug and its group, and restoring onto it revives it.
    rows = (await ctx.db.execute(select(NewsArticle))).scalars().all()
    match = match_by_identity(articles, rows, noun="article")

    categories = list((await ctx.db.execute(select(NewsCategory))).scalars())
    tags = list((await ctx.db.execute(select(NewsTag))).scalars())
    _check_slugs(ctx, "category", raw[CATEGORIES_NAME], categories)
    _check_slugs(ctx, "tag", raw[TAGS_NAME], tags)

    return Prepared(
        articles=articles,
        match=match,
        categories=raw[CATEGORIES_NAME],
        tags=raw[TAGS_NAME],
        redirects=[{**r, "locale": normalise_locale(r["locale"])} for r in raw[REDIRECTS_NAME]],
        tag_redirects=raw[TAG_REDIRECTS_NAME],
        live_categories={c.name: c for c in categories},
        live_tags={t.name: t for t in tags},
        live_links=await _links(ctx.db, [r.id for r in match.rows.values() if r.id is not None]),
    )
