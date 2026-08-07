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
| `GET /api/news/articles?limit&offset&category&undated_first` | anonymous; published only |
| `GET /api/news/categories` | anonymous; published only |
| `POST /api/news/articles` | `news.edit` |
| `PUT /api/news/articles/{id}` | `news.edit` |
| `DELETE /api/news/articles/{id}` | `news.edit` |

Reads are anonymous because the feed block runs on public pages. Listing is
ordered newest first with undated articles last; `undated_first=true` flips
the undated to the front, which is what the admin list uses so work in
progress is not buried on the last page. An editor additionally sees
articles whose page is still a draft. Each item carries `page_status` —
the workflow state of the page behind it, which the admin list renders as a
badge; without `news.edit` it is always `published`.

`PUT` is a **partial** update: a field you omit is left alone. Sending
`published_at` as an explicit `null` is different from omitting it — that
undates the article, which is a real state rather than an error.

`DELETE` detaches the metadata; the page and its body stay.

## Design note: no foreign key

`news_articles.page_id` carries no database foreign key. The framework gives
every module its own `MetaData`, so a cross-module `ForeignKey` cannot resolve
its target table, and pagebuilder publishes no page-deleted event to hang a
cascade on either.

Two things make that safe. Every listing inner-joins the page, so an article
whose page was deleted stops appearing immediately rather than rendering a card
that links nowhere. And the orphan is then removed rather than merely hidden —
by a `PageDeleted` subscription first, and by a sweep at application startup
when that event is missed.

The sweep is not belt-and-braces. The event bus logs a handler failure instead
of raising it, and pagebuilder has already committed the page deletion by the
time the handler runs, so a dropped event leaves the row behind with nothing to
retry it. An invisible orphan does not stay invisible either: SQLite reuses a
deleted row's id, so the row would re-attach to whatever page is created next
and list one article's category and date against another article's page.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
