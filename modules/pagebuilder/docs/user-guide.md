# PageBuilder user guide

PageBuilder's screens sit under **Site** in the app sidebar: **Pages**, **Site
layout**, **Media library** and **Import / Export**. Every signed-in user can open
the first three; **Import / Export** is listed for, and opens to, only a holder of
`pagebuilder.publish` or `pagebuilder.approve` (anyone else gets a 403). What you
can *do* depends on three permissions:

| Permission | Lets you |
|---|---|
| `pagebuilder.edit` | create and save pages, **Submit for review**, restore revisions and trashed pages, **Delete forever**, edit the site layout, upload and describe media |
| `pagebuilder.publish` | **Publish**, **Unpublish**, set a schedule; open **Import / Export** and take, upload, download, delete and stage (**Restore…**) snapshots |
| `pagebuilder.approve` | **Approve** or **Reject** a submitted page, see **Pending review**; open **Import / Export** to see the snapshots and the staged restore, and apply or reject it |

The suggested roles are `pagebuilder_editor` (edit), `pagebuilder_publisher`
(edit + publish) and `pagebuilder_approver` (all three). The editor shows the
buttons a page's *status* allows; a button your role does not cover answers with
an error rather than being hidden.

## Pages (`/pagebuilder/`)

The list shows **Title**, **Slug**, **Language** (multilingual sites only), **Status**
and **Updated**, with
**Search pages** (title or slug), a status filter (**All**, **Drafts**,
**Published**, **In review**) and, on a multilingual site, a language filter
(**All languages**). **Board view** groups the same pages into **Draft**,
**Scheduled**, **In review** and **Published** columns; **List view** switches
back. Row actions are **Edit**, **View** (published pages), **Translate** and
**Delete**. Links at the top lead to **Pending review**, **Trash**, **Site
layout** and **Media library**.

### Creating a page

**New page** asks for:

| Field | What it means |
|---|---|
| **Title** | The page's name inside the site; also the browser title unless a meta title is set. |
| **URL** | The slug, derived from the title and editable: lowercase letters, digits and `-`, starting with a letter or digit, up to 200 characters. |
| **Language** | Only on a multilingual site. *Fixed once the page exists.* |
| **Parent** | Optional. Affects the breadcrumb, not the URL. Only pages in the same language are offered. |
| **Start from** | **Blank**, **Templates** (pages flagged as templates) or **Copy a page**. The source's *draft* is copied, once; later edits to it never reach the copy. |

**Create and open editor** creates a draft. A slug already used in that language
is refused.

### The editor (`/pagebuilder/{id}/edit`)

Drag blocks from the palette onto the canvas and edit their fields on the right.
Changes autosave as a draft (the toolbar shows **Saving…**, **Saved at …** or
**Save failed**); **Save draft** saves now. Saving never changes the live page.

The toolbar's buttons follow the page's status:

| Status | Buttons |
|---|---|
| Draft | **Submit for review**, **Publish** |
| Submitted for review | **Reject**, **Approve**, **Publish** |
| Published | **Unpublish**, **Publish** (publishes the current draft over the live copy), **View** |

The toolbar also has **Settings** (opens the inspector below) and **History (n)**.
**Publish** asks for an optional note (**Describe this publish**), recorded on the
revision. **Reject** requires a **Reason for rejection**; the editor sees it in
the page header (**Rejected:** …) and in the history. **Approve** publishes
immediately. On a narrow screen the canvas is read-only: you can still
**Preview the draft**, reorder blocks in the **Outline**, schedule and publish.

The **page** tab of the inspector also offers **Duplicate page** (a draft copy at
`<slug>-copy`), **Save as template**, which offers the page under **Start from**
in **New page**, and **Delete page**.

**Settings** opens the inspector, which has up to three tabs:

- **page** — **Title**, **URL**, **Parent page**, **Navigation** (**Show in
  header nav**, **Show in footer**), **Visibility** (**Allow indexing**).
- **SEO** — see [SEO](#seo) below; it also holds the **Schedule**.
- **languages** — the page's translations, shown only on a multilingual site; see
  [Languages](#languages).

### Lifecycle

```
draft ──Submit for review──▶ submitted_for_review ──Approve──▶ published
  ▲  ◀─────────Reject (reason required)─────────┘                  │
  └───────────────────────────Unpublish──────────────────────────────┘
draft ──Publish──▶ published          (publish is allowed from any status)
```

- **Unpublish** takes the page offline: its address answers 404 at once, and
  the content is kept as a draft you can republish.
- Submitting a page that is already in review is refused; the approver owns it
  until they approve or reject.
- **Preview** (`/pagebuilder/{id}/preview`) renders the *draft* exactly as a
  visitor would see it, inside the site layout. It stays behind sign-in and is
  always `noindex`. A bar across the top says **Preview — this draft is not
  published**, shows the page's status and links **Back to editor**; visitors
  never see it.

### What visitors see when a page is missing

An address with nothing to show — a typo, a draft, a page in the trash, or one
scheduled but not yet live — answers **404** with the site's own not-found
page: your header and footer, your branding, the words *This page doesn't
exist* in the address's language (`/de/p/…` is German), and a button back to
the home page (`/`). Every cause gets exactly the same page, so it never
reveals that a draft exists, and it is never cached. A renamed page still
redirects to its new address instead.

Every public page also has a **Skip to content** link for keyboard users (the
first thing Tab reaches), keeps its footer at the bottom of the window on a
short page, and prints without the header and footer — the page's address
is printed at the top instead.

### Scheduling

In **Schedule** (on the **SEO** tab; **Save schedule** or **Clear** applies it),
**Publish at** auto-publishes a *draft* at that time, and
**Unpublish at** reverts a *published* page to draft. Either, both (a bounded
campaign) or neither; **Unpublish time must be after publish time.** Each is
cleared when it fires, and a manual **Publish** or **Unpublish** clears the
matching one. The flip happens on the scheduler's next tick (every 30 seconds by
default), recorded in the history as "Auto-published on schedule". A page in the
trash never goes live on its schedule.

### History and revisions

**History (n)** lists one revision per transition — **Published**,
**Unpublished**, **Submitted for review**, **Approved**, **Rejected** — with who,
when and the note. Saving a draft does not add one. **Compare** shows a
block-level diff (**Added**, **Changed**, **Removed**, **Metadata**) between two
revisions. **Restore as draft** copies a revision's title, meta description,
social image and blocks into the draft; the live page is untouched until you
publish.

A snapshot restore (see Import / Export) writes no revision, so the list also
shows **Restored from snapshot #N** at the time it was applied and by whom,
with "The restore created this page." when the page did not exist before, and
"The same restore also changed: News (3)" when the same restore wrote another
module's content (a count, never which rows). It has no **Compare** or
**Restore as draft**: to undo it, restore the automatic snapshot taken just
before it.

### Slugs and redirects

Changing the URL of a saved page leaves a permanent (301) redirect from the old
address — *Saving leaves a permanent redirect from …, so existing links keep
working.* Renaming again moves the redirect, renaming back to an old slug never
creates a loop, and a chain of renames always lands on the current address in one
hop. A redirect only forwards to a page that is live: while the page is
unpublished, scheduled, in review or in the Trash, its old address answers 404
rather than sending visitors to a dead URL, and it forwards again once the page
is republished. Redirects belong to the page's language. A trashed page keeps
its slug, so no new page can take its address while it waits in the trash.

### Delete, trash and purge

**Delete** moves a page to the **Trash** for 30 days. Deleting a *published* page
asks you to type its slug, because its address starts answering 404 the moment
you confirm. In **Trash** (`/pagebuilder/trash`):

- **Restore** brings the page back **as a draft**, never straight back to
  published; its previous published copy is kept, so republishing is one click.
- **Delete forever** removes the page and its revision history and redirects.
  It cannot be undone. Other modules are told, so they drop what they kept
  about the page.

Pages past the 30 days are removed automatically.

## Pending review (`/pagebuilder/pending`)

Approvers see every page in review with **Title**, **Slug** and **Submitted**.
**Approve** publishes at once; **Reject** sends it back to draft with a reason;
**Review** opens the editor.

## SEO

| Field | Behaviour |
|---|---|
| **Meta title** | Title for search results and link previews. Blank uses the page title. |
| **Meta description** | `<meta name="description">` and `og:description`. |
| **Social image** | `og:image` / `twitter:image`, 1200×630 recommended. Paste a URL from the media library. Blank falls back to the first **Image** block on the page; a `/media/…` path is sent as an absolute URL. |
| **Canonical URL** | Blank uses the page's own absolute URL. Override only when the content is hosted elsewhere. Never copied to a translation. |
| **Allow search engines to index this page** | Off emits `noindex,nofollow` and removes the page from `/sitemap.xml`. Whether the page is public at all is its publish state. |
| **JSON-LD structured data** | A JSON *object*, embedded in a `<script type="application/ld+json">` tag. Invalid JSON is refused in the panel. |

**As it appears** previews the search result. Published pages are listed in
`/sitemap.xml` (indexable ones only), and a page with published translations
emits `hreflang` links for each plus `x-default`.

## Languages

On a site configured with more than one content language, a page is written in
**one** language for its lifetime. To publish it in another, create a
**translation**: an ordinary page with its own URL, draft, schedule and approval,
linked to the original. Publishing one never publishes another, and deleting one
leaves the others.

- From the list: **Translate** on a row → pick a **Language** (only the ones
  still free are offered) → optionally untick **Copy this page's content** →
  **Create and open editor**.
- From the editor: the **languages** tab lists every language, which ones the
  page exists in (**Live**, **Draft**, **In review**, **In trash**) and their
  addresses; **Add translation** starts a missing one. Save the page first.

A new translation starts as a draft with the source's title (untranslated, so
what is left to do is obvious), the same slug where it is free in that language
(else `-2`, `-3`…), the same nav flags, and its parent's own counterpart as
parent. The default language serves at `/p/{slug}`; others at
`/{language}/p/{slug}` (for example `/de/p/about`). A language whose page is in
the trash stays occupied until that page is restored or purged.

## Site layout (`/pagebuilder/layout`)

The header and footer wrapped around every published page, edited with the same
drag-and-drop editor and a smaller palette (**Site chrome**: site header and
footer, plus headings, text, image, button, logo cloud, spacer and divider).
**Save layout** records a revision (a save with no change records none);
**History (n)** lists them and **Restore** puts one back. A layout change reaches
every page at once.

### Navigation flags

**Show in header nav** and **Show in footer** on a page add it to the site
header's or footer's links. Only *published* pages in the *same language* as the
page being viewed are added, labelled with their title and sorted
alphabetically. They are appended **after** the layout's own links, and a page
the layout already links to (same address, ignoring a trailing `/`) is not added
twice. **Order is the layout's**: to put a page somewhere specific, link it there
in the layout editor and the flag stops adding a second copy.

## Media library (`/pagebuilder/media`)

Images available to every page. **Upload** (or drop files on the page) into a
folder (**Upload to folder**, e.g. `marketing/heros`; blank means **Unfiled**).
JPEG, PNG, GIF and WebP up to 10 MB are accepted by default; the file's contents
must match its type. Each upload gets WebP thumbnails (320, 640, 1280 and 1920 px
wide, never wider than the original) used for responsive images.

Browse by **Folders**, filter by **Search** (filename), **Type**, **Min KB** and
**Max KB**. **Copy URL** copies an image's address (useful for **Social image**).
**Details** opens the asset (`/pagebuilder/media/{id}`), where you set **Alt
text**, **Caption** and **Credit**, and see where it is **Used in**. Alt text
describes the picture, so it is the default wherever the image is placed next.
**Delete asset** is refused while any non-trashed page (draft or published) still
uses the image, and names the pages to detach it from.

In the editor, image fields offer **Browse media…**, drag-and-drop **Upload**, or
a pasted URL.

## Import / Export (`/pagebuilder/content`)

**Take snapshot** captures the whole site as a restore point: every non-trashed
page (templates included) in every language, page redirects, the site layout and
the media files — and the content of every module that contributes to the
bundle. News does: its articles, categories, tags and their redirects ride
along (see the news user guide). It does **not** hold branding, trashed pages
or revision history. Each snapshot is marked **Taken here**, **Uploaded** or
**Automatic, before a restore**, and its row lists each contributed section's
counts ("News — Articles: 12 · Categories: 3 · …"). **Download** exports it as a
`.zip`; **Upload bundle…** adds a `.zip` from another site. A bundle includes
draft and scheduled articles and their bylines: treat a downloaded bundle like a
database export.

**Restore…** never applies directly. It stages a plan — pages **Created**,
**Overwritten**, **Unchanged**, redirects, layout, media, then one card per
contributed section with its own lines (for news: articles new, overwritten,
brought back from the trash, moved back to their snapshot address, unchanged,
kept, categories, tags, redirects dropped) — and an approver opens **Review it**
(`/pagebuilder/content/review`) to **Approve & apply** or **Reject**. The
headline counts every overwrite, pages and contributed rows together. One
restore can wait at a time. Applying first takes an automatic snapshot of the
current site, contributed sections included, so it can be undone; the result
says what each section wrote, and a page's history notes what the same restore
wrote elsewhere ("The same restore also changed: News (3)"). Restoring never
deletes: a page or article on the site but absent from the snapshot is left
alone, and a redirect whose target is missing is dropped and listed.

The screen offers only what you may do: **Take snapshot**, **Upload bundle…**,
**Download**, **Restore…** and **Delete** need `pagebuilder.publish`, so an
approver without it sees the list and **Review it**, and nothing else.

### Who sees and restores a contributed section

A contributed section declares its own permissions; pagebuilder enforces them
without knowing the module. For news:

| To … | you need, beyond pagebuilder's own |
|---|---|
| have your snapshot include the articles, or download a bundle that carries them | `news.edit` |
| see the articles' titles and addresses in a staged restore | `news.edit` |
| restore the articles (staging *and* approving) | `news.edit` and `news.publish` |

- A snapshot taken without `news.edit` leaves news out, and its row says so
  ("News is not in this snapshot: whoever took it did not hold news.edit").
  Restoring it leaves the live articles alone.
- **Who may see a staged restore:** the review screen and the pending banner
  need `pagebuilder.publish` or `pagebuilder.approve`. A reader without
  `news.edit` sees the news card's counts only, with "only the counts are shown
  here. Seeing the details needs news.edit." Article titles and slugs are never
  stored on the audited import row; they are served only to readers allowed to
  see them.
- Staged by someone without `news.edit` and `news.publish`, news is not planned
  at all: the plan says "News is left out of this restore", and it stays out
  even if the approver could restore it — stage again as someone who can.
- An approver who lacks them restores the pages only; the result names the
  section left out.
- Other markers: "This bundle also carries *x* content, which this site cannot
  restore" (no module here reads that section — it is kept in the bundle and
  downloads again unchanged), "*News* is not in this bundle and stays as it is"
  (a bundle from before the section existed), and "the details of this plan
  could not be read" (the staged rows went missing on disk; the counts stand).

A bundle from a newer build with a format this one does not understand is
refused on upload with a message naming the version; the format is described in
[bundle-format.md](bundle-format.md).

## The block palette

Blocks are grouped in the editor's palette; another module can add its own
category. A summary, not every field:

| Category | Blocks (palette labels) |
|---|---|
| typography | Heading, Text, Markdown, Prose section, Quote, List, Definition list |
| media | Image, Image gallery, Carousel, Video, Iframe |
| actions | Button, Action List, Colored action list, App store badges |
| layout | Columns, Container, Row, Column, Grid, Spacer, Divider |
| **Sections** | Page header, Hero, Eyebrow + heading + body, Media object, Call to action, Section intro, Feature showcase, Steps, Timeline |
| **Collections** | Feature cards, Feature card, Feature grid, FAQ, Statistics, Article cards, Contact Cards, Logo cloud, Story cards, Testimonials, Leaderboard, Table |
| **Forms** | Contact form, Tags, Newsletter signup, Signup banner |
| **Interactive** | Accordion, Tabs |
| **Utility** | Raw HTML, Alert, Social banner, Under Construction, Welcome |

The first four groups have no translated title; Puck shows their key. Several
labels carry a hint in brackets in the palette (for example "Feature cards
(linked grid)"). A page's root also has a **Contained** / **Full width** choice.

**Iframe** embeds a URL, sandboxed by default (**Sandbox (block popups &
navigation)**). **Raw HTML** renders inside a sandboxed iframe with scripts
disabled. Site header and footer are only offered in the site layout.

## Markdown

The **Markdown** block renders a small, safe subset:

- `# `, `## `, `### ` headings (one level per line);
- paragraphs separated by a blank line;
- `- ` bullets and `1. ` / `1) ` numbered lists; indenting an item nests it
  under the one above (a tab counts as four spaces); a top-level numbered list
  keeps its starting number (`3.` starts at 3), a nested one always starts at 1; switching between `-` and `1.` at the top
  level starts a new list; only `1.` can interrupt a paragraph, so a wrapped line
  starting "2019. …" stays prose;
- `**bold**`, `*italic*`, `***both***` and `` `code` ``;
- links `[label](url)`, images `![alt](src)` and linked images
  `[![alt](src)](url)`.

Safety: a link becomes an anchor only for `http`, `https`, `mailto`, `tel` or a
scheme-less (relative or `#anchor`) address; an image loads only from `http`,
`https` or a relative path. Anything else (`javascript:`, `data:`, a URL with a
control character) stays visible as literal text. External links open in a new
tab with `noopener`. No raw HTML is interpreted.

Many other blocks' multi-line text fields accept the same inline syntax and
lists; there, `#` headings render as bold paragraphs so the page's heading order
is not broken, and a single line break is kept as a line break.
