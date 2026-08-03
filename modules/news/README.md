# simple_module_news

News articles for SimpleModule hosts, backed by page-builder pages.

An article **is** a page. Its title, slug, body, approval workflow, revisions
and public URL all belong to `simple_module_pagebuilder`; this module adds only
the two things a page has no concept of — the category it belongs to and the
date it should be listed under — plus the listing API and a feed block.

That is why there is no public route here. An article serves at `/p/{slug}`
with the existing ETag, cache, CSP, SEO and site-layout handling; a second
viewer would mean duplicating all of it.

## Installation

```bash
pip install simple_module_news
```

The host must also install `simple_module_pagebuilder`. For an in-repo
checkout, resolve it from the workspace:

```toml
dependencies = ["simple_module_news"]

[tool.uv.sources.simple_module_news]
workspace = true
```

Then run `make migrate` — the module's first revision is labelled `news`, so it
can be removed on its own with `alembic downgrade news@base`.

## Usage

Go to **News** in the sidebar. "New article" creates a page, attaches the
article metadata to it, and drops you into the page-builder editor to write the
body. Category and date are edited inline in the list.

To show articles on a page, add the **News feed** block in the page builder and
set its category filter and item count.

### API

| Route | Access |
|---|---|
| `GET /api/news/articles?limit&offset&category` | anonymous; published only |
| `GET /api/news/categories` | anonymous; published only |
| `POST /api/news/articles` | `news.edit` |
| `PUT /api/news/articles/{id}` | `news.edit` |
| `DELETE /api/news/articles/{id}` | `news.edit` |

Reads are anonymous because the feed block runs on public pages. Listing is
ordered newest first with undated articles last, and an editor additionally
sees articles whose page is still a draft.

`DELETE` detaches the metadata; the page and its body stay.

## Design note: no foreign key

`news_articles.page_id` carries no database foreign key. The framework gives
every module its own `MetaData`, so a cross-module `ForeignKey` cannot resolve
its target table, and pagebuilder publishes no page-deleted event to hang a
cascade on either.

What makes that safe is that every listing inner-joins the page: an article
whose page was deleted stops appearing immediately rather than rendering a card
that links nowhere. The row itself is inert until something detaches it.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
