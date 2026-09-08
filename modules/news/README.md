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

Articles serve at `/news/{slug}` (the `public_route_prefix` setting), so an article
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

**One caveat, on the frontend.** A bundler resolves imports statically, and that
includes *dynamic* ones — Rollup errors on an unresolvable `import()` exactly as
it does on a static `import`, so the `try`/`catch` around it never runs and no
amount of guarding inside this module makes the dependency conditional. So
`news/puck-blocks.ts` — and the `NewsFeed` component it pulls in — genuinely do
import `@simple-module-py/pagebuilder` at build time. They are the only two
files in this module's frontend that do, and `@simple-module-py/pagebuilder` is
declared an *optional* peer dependency so npm does not demand it. A host that
installs news without pagebuilder should exclude `puck-blocks.ts` from its block
glob (see `host/client_app/blocks.ts`); there is no feed block to register
without the palette it registers into. Every other screen — the list, both
editors, the public viewer — builds and runs with the package absent.

The real fix belongs to the framework rather than here: `gen-pages` already
emits the page globs, and could emit the block imports too, skipping a module
whose optional peers do not resolve — once, for every host and every module.

## Usage

Go to **News** in the sidebar. "New article" creates the article and drops you
into its **body canvas** — this module's own block editor — to write it.
Headline, URL, category, tags, byline, display date and feed behaviour are
edited on the **article screen**; the list edits category and date inline. A
live article whose draft has moved on since it was published is marked
**Unpublished edits** in the list, because "Published" on its own is a true
sentence about a document nobody is looking at.

The article screen also carries **Review** (submit, approve, send back with a
note), **Schedule**, **Search & sharing** and **History**. Binned articles are
under **News → Trash**, where they can be restored or removed for good.

The two screens split by posture, not by importance: the canvas wants the whole
viewport and autosaves on a timer, and the article screen is a column of short
fields saved by one button. The headline lives on the article screen rather than
on the canvas because moving it also moves the URL, and a rename is a decision —
not something that should happen on a debounce.

## The reader's side

`/news/` is the archive: published articles, newest first, twelve to a page,
with `/news/category/{slug}`, `/news/tag/{slug}` and `/news/author/{slug}`
narrowing it, `?q=` searching within whichever of those you are on, and
`/news/feed.xml` carrying the recent run as RSS.

Search narrows the page it was typed on rather than replacing it, which is why
there is no `/news/search`: a reader on a category page is standing somewhere
that already promises a scope, and answering a question they did not ask by
silently widening to the whole archive is worse than answering the one they
did. Results are `noindex, follow` — the input space is unbounded, so one
indexed `?q=` invites a crawler to enumerate query strings forever, while the
links *out* of a result page are the real documents and worth following.

It searches headline, slug, excerpt and tags, and deliberately **not** the
body. Not for cost: the body column the admin's search scans is `draft_data`,
so a public search over it would answer for text nobody has published — a
phrase living only in an unpublished edit would surface the article and tell an
outsider that the edit exists.

An author becomes an address through the same slug rule as everything else, so
two spellings of one byline (`A. Subash`, `A Subash`) share one page rather
than one of them disappearing: that is nearly always one person entered
inconsistently, and two genuinely different people are an editorial fix that
costs nothing. A byline with no ASCII to fold onto has no address at all and
renders as plain text — a missing feature, chosen over the slugifier's fallback
collapsing unrelated writers onto a single archive claiming to be each of them.

None of that existed until recently, and its absence was the hole in the middle
of the split. The public router had exactly one route — `/{slug}` — so a reader
could open an article they already had a link to and nothing else: `/news/`
answered 404, the bare `/news` bounced an anonymous visitor to the sign-in
screen, and the only browsing surface in the codebase was the **News feed**
block, which registers into *pagebuilder's* palette. A module that could be
installed alone could not be read alone.

Paging is real links rather than "load more", because the pager is how a
crawler reaches everything past the first page. A page beyond the end is a 404
rather than an empty document, so a crawler guessing `?page=900` is told there
is nothing there instead of being handed something valid-looking to index.

The *first* page of a narrowing that matches nothing is the opposite case, and
the two are easy to confuse. An unknown tag, a byline nobody wrote under, or a
search with no hits all render an empty archive with a way back: the address is
meaningful and simply holds nothing today — a tag can be removed from the last
article carrying it, and a URL published while it existed should say "nothing
here now", not "never existed". Page *900* of that same empty tag is still a
404, because there is no reading under which it has one.

### Metadata a crawler can read

Articles and archive pages carry a server-rendered `<head>` — `<title>`, the
description, `og:*`, `twitter:*`, the canonical link, `robots` and JSON-LD —
written into the document before it leaves the server.

They have to be, because the host renders one Inertia shell for every screen: a
fixed `<title>` and an `{% inertia_head %}` slot that only fills under SSR,
which nothing configures. `PublicArticle.tsx` composes all of those tags through
Inertia's `<Head>`, and every one of them existed only after the bundle ran.
Google executes JavaScript; Slack, X, LinkedIn, Facebook and most feed tooling
do not — so an article link previewed as "SimpleModule" with no description and
no image, and an article marked `index_in_search=false` was indexed anyway
because the `noindex` never reached the crawler either.

`endpoints/public/_head.py` writes them in on the way out. The tags are
duplicated with the client-side ones on purpose: one copy serves the crawler
that never runs the script, the other serves the reader who arrived through the
SPA and never reloaded, and neither covers the other's case. If the host ever
adopts SSR, `{% inertia_head %}` starts emitting the same tags and that module
should be deleted rather than made cleverer.

## Permissions

| Permission | Grants |
|---|---|
| `news.view` | see the admin list |
| `news.edit` | create, write and edit articles; submit for review |
| `news.publish` | publish, unpublish, approve, reject, purge, hard delete |

`news.publish` is separate on purpose. Publishing used to require
`pagebuilder.publish`, because the write landed on one of its pages and news was
not entitled to route an author past that module's editor → publisher
separation. Owning the content means owning the separation: folding it into
`news.edit` would hand every author a way past a review step a host may want.

### API

| Route | Access |
|---|---|
| `GET /news/` | anonymous; the archive, paged |
| `GET /news/category/{slug}` | anonymous |
| `GET /news/tag/{slug}` | anonymous |
| `GET /news/{slug}` | anonymous; published articles only |
| `GET /{locale}/news/{slug}` | anonymous; one mount per non-default content locale |
| `GET /news/feed.xml` | anonymous; RSS 2.0, most recent 20 |
| `GET /news/sitemap.xml` | anonymous |
| `GET /api/news/articles?limit&offset&category&q&status&in_feed&locale&translation_group&undated_first` | anonymous; published only |
| `GET /api/news/categories` | anonymous; published only |
| `GET /api/news/articles/{id}/tags` | anonymous; published only |
| `POST /api/news/articles` | `news.edit` |
| `POST /api/news/articles/{id}/translations` | `news.edit` |
| `PUT /api/news/articles/{id}` | `news.edit` |
| `DELETE /api/news/articles/{id}` | `news.edit` **+ `news.publish`** |
| `GET /api/news/articles/{id}/detail` | `news.edit` |
| `PUT /api/news/articles/{id}/body` | `news.edit` |
| `GET /api/news/articles/{id}/revisions` | `news.edit` |
| `POST /api/news/articles/{id}/revisions/{rev}/restore` | `news.edit` |
| `POST /api/news/articles/{id}/submit` | `news.edit` |
| `POST /api/news/articles/{id}/trash` \| `/restore` | `news.edit` |
| `POST /api/news/articles/{id}/publish` \| `/unpublish` | `news.edit` **+ `news.publish`** |
| `POST /api/news/articles/{id}/schedule` | `news.edit` **+ `news.publish`** |
| `POST /api/news/articles/{id}/approve` \| `/reject` | `news.edit` **+ `news.publish`** |
| `DELETE /api/news/articles/{id}/purge` | `news.edit` **+ `news.publish`** |

Reads are anonymous because the feed block runs on public pages. Listing is
ordered pinned first, then newest, with undated articles last;
`undated_first=true` flips the undated to the front, which is what the admin
list uses so work in progress is not buried on the last page. An editor
additionally sees drafts. Each item carries `status`, which the admin list
renders as a badge; without `news.edit` it is always `published`.

An editor's items also carry `has_unpublished_changes` — the article is live
and its draft has since moved on, so what you are looking at is not what
readers are served. Only for a caller who may see drafts: it is a statement
about work in progress, and the column behind it is not even selected for
anyone else. It is compared, not inferred from a timestamp, and it is false for
a *draft* holding an old snapshot — there is nothing live there to diverge
from.

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

### Scheduling

`POST /articles/{id}/schedule` sets `publish_at` and `unpublish_at`: a draft
goes live by itself at the first, a published article comes down by itself at
the second. Both are optional and both are three-valued — an omitted field is
left alone, an explicit `null` cancels. Behind `news.publish`, because a
schedule is a publication decision that happens to be about the future.

An in-process loop (`scheduler_enabled`, every `scheduler_interval_seconds`)
calls `ArticlesService.process_due`. The query is `<= now` rather than "since
the last tick", so a process that was asleep catches up rather than losing the
window; each timestamp is cleared when acted on, so a tick cannot republish the
same article forever.

#### Running more than one of them

The loop starts in *every* process that boots the module, so `uvicorn -w 4`,
gunicorn with workers and a Deployment with `replicas > 1` all run several. That
is safe: before touching a due article, `process_due` **claims** it with one
conditional statement whose own effect takes it out of the due set —

```sql
UPDATE news_article SET publish_at = NULL
 WHERE id = :id AND deleted_at IS NULL AND status = 'draft'
   AND publish_at IS NOT NULL AND publish_at <= :now
```

— and acts only if that updated a row. The check and the claim are one
statement, so the database decides the winner: whichever replica runs second
meets a row that no longer matches and moves on. One PUBLISH revision row per
article, and no flip-flop on the way down. An external worker driving
`process_due` alongside the loop is safe for the same reason.

Row claiming rather than `SELECT … FOR UPDATE SKIP LOCKED`, which is
Postgres-only and would do nothing on SQLite, this repo's local-dev default; and
rather than a lease table, which elects one scheduler for the whole app and buys
a migration, a clock comparison and a window after a leaseholder dies in which
nothing publishes. A claim here lives in the tick's transaction, so a process
that dies mid-flip releases it and the article is simply due again. See
`news/content/_claims.py`.

What it does **not** cover: N replicas still each poll the database every
`scheduler_interval_seconds`, and each still reads its own clock — an article
goes live when the first replica to think it due acts, so a badly skewed clock
moves that by the skew, exactly as the poll interval already does. Where either
matters, set `scheduler_enabled` false everywhere and drive `process_due` from
one place — a cron job, a k8s CronJob, a dedicated worker. Set it on the
Settings screen or with `scripts/set_setting.py news scheduler_enabled false`,
never an environment variable, which this module does not read.

These are deliberately **not** `published_at`, which is the display date below
and may perfectly reasonably be in the past. The article screen said "a future
date lists this as scheduled" for a while, which read as a promise nothing kept.

`published_at` is a **display date**, not a timestamp. Whatever instant you
send, the day is taken as you wrote it and stored as midnight UTC — sending
`2026-02-01T23:00:00-06:00` records the 1st, not the 2nd. It is also independent
of `status`: an article can be published and undated, or dated and still a
draft.

## Multilingual articles

An article is a page, so its language is the page's language — configured in
pagebuilder (its `content_locales` setting), not here, because a language
news offered that pagebuilder did not would be one no article could be written
in. Off by default: with one content locale every article URL is exactly what
it was.

Articles in the default language keep `/news/{slug}`; every other language is
prefixed, `/de/news/{slug}`. `ArticleRead.url` carries the prefix, so the admin
list, the feed block and the slug news claims from pagebuilder all agree on
one address. `/{default}/news/{slug}` permanently redirects to the bare form.

`?locale=de` narrows a listing to one language — what a feed block on a German
page passes, so a German list never shows an English card. The block reads the
surrounding page's language rather than offering it as a field: a feed set to
one language on a page written in another is a mistake nothing would catch.
The admin list leaves it unset and shows every language, badged per row.

`POST /articles/{id}/translations` starts the same story in another language:
one request, one transaction, creating both the translated page and the sidecar
row. Category, byline, date, pin and feed membership are copied from the source
rather than asked for again — they are facts about the story, not about the
language it is told in. The translation starts as a draft.

`?translation_group=…` lists one article and its counterparts, which is what
the editor's language switcher shows. It goes through the ordinary listing
rather than a route of its own, so it inherits the same visibility rule: a
reader without `news.edit` sees the published translations only.

Anonymous listings carry `Cache-Control: public, max-age=60`, because the feed
block runs on every public page that holds one. An editor's listing includes
drafts and so is `private, no-store`. The article viewer sends an `ETag`,
`Cache-Control: public, max-age=300, stale-while-revalidate=60`, and
`Content-Security-Policy` when `public_csp` is set.

## Settings

Stored in the database and edited under **Settings → News**. There is no
`SM_NEWS_*` environment variable: the settings class drops every env source, so
a value can only come from the store or from the default below. Headless
deployments write them with `scripts/set_setting.py`.

Fields marked ● are read once while the app boots — they decide which routes are
mounted and what the auth layer exempts — so changing one needs a restart. The
Settings screen says so next to the input.

| Setting | Default | What it does |
|---|---|---|
| `public_route_prefix` ● | `/news` | where articles serve |
| `public_base_url` | *(derived from the request)* | origin for canonical URLs and the sitemap |
| `site_name` | *(unset)* | `og:site_name` |
| `twitter_handle` | *(unset)* | `twitter:site` |
| `public_cache_max_age` | `300` | shared-cache lifetime of an article |
| `public_cache_swr` | `60` | `stale-while-revalidate` seconds; `0` omits it |
| `public_csp` | *(unset)* | `Content-Security-Policy` on the article page |
| `scheduler_enabled` ● | `true` | run the in-process publish/unpublish loop — safe under replicas, which claim each due article; see [Scheduling](#scheduling) |
| `scheduler_interval_seconds` ● | `30` | how often it looks for due articles |

The languages articles may be written in are **not** here. They are
pagebuilder's `content_locales`, borrowed through `news.integrations.locales`
so one site does not keep two lists that can disagree. Without pagebuilder news
publishes in one language, at the unprefixed URL — the behaviour every
monolingual site already has.

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
  one of its own the whole archive would silently drop out of every index. It
  lists the archive index and every category and tag page as well as the
  articles — a sitemap of leaves says the articles exist but not that anything
  links them — and a taxonomy page only while at least one published,
  indexable, listed article in that language fills it. An empty one is a thin
  page, and a sitemap is a request to come and index.

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

- **The article *body* still needs JavaScript.** The metadata does not — see
  **The reader's side** — but the document itself is a block tree rendered by
  React, so the raw HTML carries the article's text only inside the Inertia
  data blob. A crawler that executes scripts reads it; one that does not sees
  the head and nothing else. Server-rendering the body would mean a Python
  implementation of all twenty-one blocks, or SSR in the host. Both are real
  projects; neither is this module's to start.
- **Images take a URL, not a picker.** The media library belongs to
  pagebuilder, and the Image and Gallery blocks have to work without it. The
  single-URL fields now show what the address points at as it is typed, so a
  wrong one is caught in the panel rather than on the published page — but that
  is a preview, not a library, and the extra step remains.

  The obvious alternative does not work. This repo's host also runs
  `file_storage`, but every one of its routes sits behind `RequiresPermission`,
  there is no static mount over `uploads/`, and `StoredFileOut` carries no
  `url` at all. An article image served from it renders in the admin preview
  and 401s for every logged-out reader — which is exactly why pagebuilder
  mounts `MediaFiles(StaticFiles)` and adds an auth-exempt prefix for its own
  media, saying so in `boot.py`: *"without this the page renders for an
  anonymous visitor but every image 302s to login."* Proxying it through a news
  route would be worse than the gap, not a shortcut: the store is shared by
  every module with no notion of "public", so a `GET /media/{file_id}` would
  make any file anyone ever uploaded anonymously readable to whoever holds the
  UUID. The fix is a public-read capability in `file_storage`, which is the
  framework's to add.
- **Nothing here is translated.** Every string is hardcoded English and there is
  no `locales/`. This is not news' to fix alone: the framework's convention
  depends on `@simple-module-py/i18n` and *this repo's host does not wire i18n
  at all* — no dependency, no loader, no generation step. Adding a catalogue to
  one module would do nothing until the host adopts it, and then all three
  modules here convert together. See the repo's `CLAUDE.md`.
- **The scheduler still polls per process.** Publishing at the right moment is
  now safe with several replicas — each due article is taken with one
  conditional `UPDATE`, so two ticks landing together flip it once — but every
  replica still wakes on its own interval. Where that traffic is unwanted,
  turning `scheduler_enabled` off and driving `process_due` from one external
  worker remains the answer. That is now a preference rather than a safety
  requirement.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
