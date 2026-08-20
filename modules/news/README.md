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
| `POST /api/news/articles/with-page` | `news.edit` |
| `POST /api/news/articles/{id}/publish` | `news.edit` |
| `PUT /api/news/articles/{id}` | `news.edit` |
| `DELETE /api/news/articles/{id}` | `news.edit` |

Reads are anonymous because the feed block runs on public pages. Listing is
ordered newest first with undated articles last; `undated_first=true` flips
the undated to the front, which is what the admin list uses so work in
progress is not buried on the last page. An editor additionally sees
articles whose page is still a draft. Each item carries `page_status` —
the workflow state of the page behind it, which the admin list renders as a
badge; without `news.edit` it is always `published`.

`POST /articles` attaches metadata to a page that already exists.
`POST /articles/with-page` is the "New article" flow: it creates the page *and*
attaches the article in one transaction, so a failure leaves neither behind.
Omit `slug` and the server derives one from the title and takes the first free
variant — `my-title`, then `my-title-2`; send one and it is used verbatim, with
a collision reported as a 409 rather than silently renamed.
`POST /articles/{id}/publish` publishes the page behind an article, which is
what the list's row menu calls.

`published_at` is a **display date**, not a timestamp. Whatever instant you
send, the day is taken as you wrote it and stored as midnight UTC — sending
`2026-02-01T23:00:00-06:00` records the 1st, not the 2nd. The column is a
timestamp only because that is what the date is carried in.

`PUT` is a **partial** update: a field you omit is left alone. Sending
`published_at` as an explicit `null` is different from omitting it — that
undates the article, which is a real state rather than an error.

`DELETE` detaches the metadata; the page and its body stay.

Anonymous listings carry `Cache-Control: public, max-age=60`, because the feed
block runs on every public page that holds one. An editor's listing includes
drafts and so is `private, no-store`.

## Design note: one seam onto pagebuilder

An article *is* a page, so depending on `simple_module_pagebuilder` is the
design rather than an accident. What is avoidable is that dependency being
*spread*, and it was: eight Python modules here imported it directly, the DTO
re-exported its `PageStatus` as part of news' own public contract, and the
frontend hardcoded its CSRF cookie name, its page API route, its editor URL and
its media library path.

It now arrives through `news/integrations/pagebuilder.py`, the only module here
that imports that package — asserted by a test, because a single convenient
import is exactly the kind of thing that quietly undoes a rule like this.
Concretely:

- news names its own `ArticleStatus`. Same values, so the wire format is
  unchanged; `test_integrations` fails if the two vocabularies ever drift.
- `edit_url` and the search screen's "see all" links are **served**, so no TSX
  spells out how the neighbouring module routes its own screens.
- pages are created and published through pagebuilder's *service*, inside this
  request's transaction, instead of through its HTTP API with a borrowed CSRF
  token. That is what removed the throwaway priming GET, and what makes "new
  article" atomic.

Three frontend imports remain on purpose: the Puck block registry, which is how
a block is contributed at all, and `ArticleCardsGrid` and `ConfirmDialog`,
which are shared render kit a second copy of would only make inconsistent.

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
