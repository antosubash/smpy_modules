# simple_module_news

A self-contained news archive for SimpleModule hosts.

An article is a document this module owns outright: its title, slug, body,
approval workflow, revisions, SEO and public URL are all columns and routes
here. Install it, migrate it, and a host has a working archive — no other
content module required.

It did not start that way. An article used to *be* a `simple_module_pagebuilder`
page, with this module contributing only a category and a display date beside
it. That made news uninstallable without its neighbour, made every listing a
cross-module join, and left article rows that could be orphaned by a deletion
news never saw. See **Design note: what the split changed** below.

Articles serve at `/news/{slug}` (`SM_NEWS_PUBLIC_ROUTE_PREFIX`), so an article
is distinguishable from a contact page in a URL, a log line and an analytics
report. The admin console is at `/admin/news`, not `/news`: one prefix cannot be
both a reader-facing URL and a permission-gated console.

## Installation

```bash
pip install simple_module_news
```

Nothing else is required. For an in-repo checkout, resolve it from the
workspace:

```toml
dependencies = ["simple_module_news"]

[tool.uv.sources.simple_module_news]
workspace = true
```

Then run `make migrate` — the module's first revision is labelled `news`, so it
can be removed on its own with `alembic downgrade news@base`.

### Optional: pagebuilder

```bash
pip install "simple_module_news[pagebuilder]"
```

Where a host runs `simple_module_pagebuilder` too, two conveniences light up:

- the **News feed** block joins that module's palette, so a page can list live
  articles;
- the admin search screen gains **Pages** and **Media** sections alongside
  articles, with "see all" links into that module's screens.

Neither is required, and nothing outside `news/integrations/pagebuilder.py`
imports the package — every import there is deferred and guarded, so on a host
without it `available()` is `False` and the extra sections are simply absent.
`test_module.py` spawns a subprocess to prove that importing news never imports
pagebuilder.

**One caveat, on the frontend.** A bundler cannot make a static import
conditional, so `news/puck-blocks.ts` — and the `NewsFeed` component it pulls
in — genuinely do import `@simple-module-py/pagebuilder` at build time. They are
the only two files in this module's frontend that do, and
`@simple-module-py/pagebuilder` is declared an *optional* peer dependency so npm
does not demand it. A host that installs news without pagebuilder should
exclude `puck-blocks.ts` from its block glob (see `host/client_app/blocks.ts`);
there is no feed block to register without the palette it registers into. Every
other screen — the list, both editors, the public viewer — builds and runs with
the package absent.

## Usage

Go to **News** in the sidebar. "New article" creates the article and drops you
into its **body canvas** — this module's own block editor — to write it.
Headline, URL, category, tags, byline, display date and feed behaviour are
edited on the **article screen**; the list edits category and date inline.

The two screens split by posture, not by importance: the canvas wants the whole
viewport and autosaves on a timer, and the article screen is a column of short
fields saved by one button. The headline lives on the article screen rather than
on the canvas because moving it also moves the URL, and a rename is a decision —
not something that should happen on a debounce.

## Permissions

| Permission | Grants |
|---|---|
| `news.view` | see the admin list |
| `news.edit` | create, write and edit articles; submit for review |
| `news.publish` | publish, unpublish, approve, reject, purge |

`news.publish` is separate on purpose. Publishing used to require
`pagebuilder.publish`, because the write landed on one of its pages and news was
not entitled to route an author past that module's editor → publisher
separation. Owning the content means owning the separation: folding it into
`news.edit` would hand every author a way past a review step a host may want.

### API

| Route | Access |
|---|---|
| `GET /news/{slug}` | anonymous; published articles only |
| `GET /news/sitemap.xml` | anonymous |
| `GET /api/news/articles?limit&offset&category&q&status&in_feed&undated_first` | anonymous; published only |
| `GET /api/news/categories` | anonymous; published only |
| `GET /api/news/articles/{id}/tags` | anonymous; published only |
| `POST /api/news/articles` | `news.edit` |
| `PUT /api/news/articles/{id}` | `news.edit` |
| `DELETE /api/news/articles/{id}` | `news.edit` |
| `GET /api/news/articles/{id}/detail` | `news.edit` |
| `PUT /api/news/articles/{id}/body` | `news.edit` |
| `GET /api/news/articles/{id}/revisions` | `news.edit` |
| `POST /api/news/articles/{id}/revisions/{rev}/restore` | `news.edit` |
| `POST /api/news/articles/{id}/submit` | `news.edit` |
| `POST /api/news/articles/{id}/trash` \| `/restore` | `news.edit` |
| `POST /api/news/articles/{id}/publish` \| `/unpublish` | `news.edit` **+ `news.publish`** |
| `POST /api/news/articles/{id}/approve` \| `/reject` | `news.edit` **+ `news.publish`** |
| `DELETE /api/news/articles/{id}/purge` | `news.edit` **+ `news.publish`** |

Reads are anonymous because the feed block runs on public pages. Listing is
ordered pinned first, then newest, with undated articles last;
`undated_first=true` flips the undated to the front, which is what the admin
list uses so work in progress is not buried on the last page. An editor
additionally sees drafts. Each item carries `status`, which the admin list
renders as a badge; without `news.edit` it is always `published`.

`POST /articles` creates the article in one insert. Omit `slug` and the server
derives one from the title and takes the first free variant — `my-title`, then
`my-title-2`; send one and it is used verbatim, with a collision reported as a
409 rather than silently renamed. Trashed articles keep their slugs claimed.

`PUT /articles/{id}` is a **partial** update covering the listing metadata, the
identity (`title`, `slug`) and the SEO fields. A field you omit is left alone.
Sending `published_at` as an explicit `null` is different from omitting it —
that undates the article, which is a real state rather than an error. Changing
`slug` records a redirect, so the old address keeps working.

`PUT /articles/{id}/body` is the canvas autosave, and deliberately cannot reach
the slug or the status: it fires on a timer rather than on a person pressing
something.

`published_at` is a **display date**, not a timestamp. Whatever instant you
send, the day is taken as you wrote it and stored as midnight UTC — sending
`2026-02-01T23:00:00-06:00` records the 1st, not the 2nd. It is also independent
of `status`: an article can be published and undated, or dated and still a
draft.

Anonymous listings carry `Cache-Control: public, max-age=60`, because the feed
block runs on every public page that holds one. An editor's listing includes
drafts and so is `private, no-store`. The article viewer sends an `ETag`,
`Cache-Control: public, max-age=300, stale-while-revalidate=60`, and
`Content-Security-Policy` when `SM_NEWS_PUBLIC_CSP` is set.

## Settings

All prefixed `SM_NEWS_`:

| Setting | Default | What it does |
|---|---|---|
| `PUBLIC_ROUTE_PREFIX` | `/news` | where articles serve |
| `PUBLIC_BASE_URL` | *(derived from the request)* | origin for canonical URLs and the sitemap |
| `SITE_NAME` | *(unset)* | `og:site_name` |
| `TWITTER_HANDLE` | *(unset)* | `twitter:site` |
| `PUBLIC_CACHE_MAX_AGE` | `300` | shared-cache lifetime of an article |
| `PUBLIC_CACHE_SWR` | `60` | `stale-while-revalidate` seconds; `0` omits it |
| `PUBLIC_CSP` | *(unset)* | `Content-Security-Policy` on the article page |

## Design note: what the split changed

The sidecar was a real design with real reasons — it kept pagebuilder a generic
CMS that knew nothing about news, and it meant articles inherited a mature
editor, viewer and workflow for free. What it cost was independence, and three
specific hazards that are now structurally impossible:

- **No orphans.** `news_articles.page_id` was an unenforceable pointer into
  another module's table: the framework gives every module its own `MetaData`,
  so a cross-module `ForeignKey` could not resolve. A deleted page left a row
  behind, and SQLite reuses ids, so that row would re-attach to whatever page
  was created next and list one article's metadata against another's document.
  A `PageDeleted` subscription and a startup sweep existed only to contain this.
  Both are gone; an article's body is its own row.
- **No cross-module join.** Every listing joined `pagebuilder_pages` and had to
  remember `load_only` to avoid dragging both block-JSON columns through the ORM
  per row. The listing is now a single-table scan over named columns.
- **A real permission boundary.** Publishing borrowed `pagebuilder.publish`;
  it is `news.publish` now, on this module's own routes.

Two things news gained that it previously borrowed, and had to grow itself:

- **Its own viewer**, carrying the ETag, cache, CSP, canonical tag and old-slug
  redirects the hand-off used to provide. `test_public_address.py` asserts each
  one, precisely because a second viewer is what the hand-off existed to avoid.
- **Its own sitemap**, at `{prefix}/sitemap.xml`. Articles used to reach a
  crawler through pagebuilder's, via a claim news registered with it; without
  one of its own the whole archive would silently drop out of every index.

One thing it deliberately did **not** grow: a clone of pagebuilder's widget
catalogue. That catalogue builds *pages* — heroes, feature grids, site
headers — and almost none of it belongs in a news story. The body canvas ships a
prose palette instead; see **The block palette** below. A host that wants the
full page-building set on an article can install pagebuilder, build the page
there, and link to it.

## The block palette

Grouped in the editor by what a writer is reaching for, which is not always what
the block renders — **Key points** and **Sources** are both lists, and neither
sits beside **List**, because someone wanting a summary box is not shopping for
a list.

| Group | Blocks |
|---|---|
| Text | Heading, Paragraph, List, Pull quote, Q&A |
| Set apart | Key points, Callout, Definitions, Sources, Read next |
| Media | Image, Gallery, Before / after, Video file, Audio clip, Embed |
| Data | Table, Key figures, Code, Timeline |
| Layout | Divider |

The bar for adding one is that **a newsroom already does this thing in a story
and currently has to fake it with a paragraph** — a summary box, a correction, a
table of figures, a dated sequence, a list of sources. A block that only changes
how something looks is a page-building widget wearing a different hat, and
belongs in the other module.

A few consequences of that bar worth knowing:

- **Callout** has a `correction` kind. A correction is an obligation a
  publication owes its readers, and one written as an ordinary paragraph is
  indistinguishable from the reporting it corrects.
- **Image** carries a `credit` separately from its caption, because they are
  different obligations — a caption explains the picture, a credit says whose it
  is, and a publication that runs the second inside the first eventually runs a
  picture with neither.
- **Timeline** takes its dates as free text. Reporting deals in "March 2024",
  "the following morning" and "some time before 2019"; a calendar control would
  force a writer to invent precision the reporting does not have.
- **Code** is not syntax-highlighted and its `language` is a label for the
  reader, not a hint to a parser. Highlighting means shipping a highlighter, and
  these render on a host that may have installed nothing else.
- **Gallery** is a grid, not a carousel — a carousel hides all but one image
  behind an interaction, costing a reader who is scrolling the pictures they
  were shown.
- **Divider** offers an asterism (`* * *`) as well as a rule. They mean
  different things: a rule separates the article from something appended to it,
  an asterism marks a change of scene *within* one continuous piece.
- **Q&A** and **Definitions** render as `<dl>` rather than as alternating
  paragraphs, because that is what they are — each question introduces the
  answer that follows it, and a screen reader announcing the pairing gives a
  listener the structure a sighted reader gets from the indent.
- **Before / after** stays two frames side by side on a phone rather than
  stacking, and is not a drag-the-handle slider. A comparison a reader has to
  scroll between is one they have to hold in their head; a slider hides half of
  each frame behind an interaction the reader may never make.
- **Video file** and **Audio clip** are for media the publication hosts itself.
  `Embed` is an `<iframe>` and so only speaks to services that publish a player;
  a reporter's own mp4 had nowhere to go before these existed. Both
  `preload="metadata"`, because an article can carry several and a reader who
  scrolls past one should not have paid for it.

### Read next is the exception

Every other block renders exactly what a writer typed into it. **Read next**
queries the listing API instead, because a related-articles list hand-typed at
publication is stale the moment the next article goes up and nobody returns to a
three-month-old story to refresh it.

That makes it the one block that has to know which article it is inside — a
"read next" offering the article you are reading is visibly broken. The viewer
passes the current slug to `<Render>` as Puck `metadata`, and the block reads it
from `puck.metadata.currentSlug`. That seam is deliberately general: it is where
any future block that needs the article rather than its own props should look.

It renders its own list rather than reusing the card grid the `NewsFeed` block
draws with, because that grid belongs to pagebuilder and this has to work
without it.

Blocks whose content is a list — List, Key points, Q&A, Definitions, Sources,
Timeline, Key figures, Gallery, Table — are edited as a textarea, one item per
line, rather than through Puck's array field, so a writer pasting a list out of
a document gets it in one action instead of clicking "add item" nine times.
`blocks/lines.ts` is that parsing, in one place, so no two blocks can disagree
about what a line means.

Two things the palette deliberately does **not** have. **Charts** would mean
shipping a charting library, and these blocks render on the public page of a
host that may have installed nothing else — a table of the figures is the
honest version. **A table of contents** would need a block to see its siblings,
which Puck does not give a `render` function; the seam that would allow it is
the same `metadata` one `Read next` uses, so it is possible, just not free.

## Known gaps

- **The public `<head>` is rendered by the browser, not the server.** Every
  `og:*` tag, the description, the canonical link, the `robots` directive and
  the JSON-LD in `PublicArticle.tsx` go through Inertia's `<Head>`, which only
  runs once JavaScript has. The raw HTML a crawler or a Slack unfurler receives
  is `<title>SimpleModule</title>` and an Inertia data blob — the article's
  content and all of its metadata are in that blob, but nothing that reads
  markup will find them. This is the host's rendering model rather than anything
  the split changed: pagebuilder's `/p/{slug}` returns an identical bare head,
  and there is no SSR anywhere in the host. It is listed here because news is
  the module it costs the most — an archive exists to be linked to — and because
  the SEO columns below cannot do their job until it is addressed, which is
  framework work rather than module work.
- **The trash has no screen.** `POST /articles/{id}/trash`, `/restore` and
  `DELETE /articles/{id}/purge` exist and are tested, but the admin list offers
  a hard delete rather than a bin, so a trashed article is currently only
  reachable over the API. Adding a trash filter to the list is the natural next
  step.
- **The body canvas has no revision UI.** Revisions are recorded on every
  transition and readable at `/articles/{id}/revisions`, with a restore
  endpoint; no screen renders them yet.
- **Images take a URL, not a picker.** The media library belongs to
  pagebuilder, and the Image and Gallery blocks have to work without it. Where
  that module *is* installed its picker hands out exactly what these want — a
  URL to paste — so the gap is the extra step, not a missing capability.
- **The SEO fields have no screen.** `meta_description`, `og_image`,
  `canonical_url`, `index_in_search` and `json_ld` are columns, accepted by
  `PUT /articles/{id}` and rendered by the viewer — the migration carried each
  one over from the page an article used to be — but nothing in the console
  sets them. Until a screen does, `meta_description` is only ever what the
  backfill left, and the listing's `excerpt` is drawn from it.
- **Submit, approve and reject are API-only.** The article screen publishes
  directly, so a host that wants the editor → publisher separation
  `news.publish` exists to enforce has to drive those three routes itself.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
