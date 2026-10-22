# PageBuilder documentation

`simple_module_pagebuilder` is the content module of a SimpleModule site. An
editor composes **pages** from a palette of blocks in a drag-and-drop editor
([Puck](https://puckeditor.com)); each page has a draft, a published copy, a
revision history and an approval workflow, and is served to anonymous visitors
at `/p/{slug}` inside a shared **site layout** (header and footer). Around that
sit a **media library** with server-generated thumbnails, per-page SEO
(canonical, noindex, JSON-LD, `hreflang`, a sitemap), multilingual content, and
**snapshots** that export the whole site as a `.zip` and restore it behind an
approval gate.

Start with the document that matches what you are trying to do.

## Who should read what

| You are | Read |
|---|---|
| An editor, publisher or approver writing and publishing pages | [user-guide.md](user-guide.md) |
| A developer calling the pagebuilder API, or presenting pages from another module | [api-reference.md](api-reference.md) |
| An operator installing it, configuring languages and the public site, or answering "why does this page 404?" | [operations.md](operations.md) |
| A developer changing the module or adding blocks | [architecture.md](architecture.md) |
| Anyone writing, reading or hand-editing a snapshot `.zip` | [bundle-format.md](bundle-format.md) |

### [user-guide.md](user-guide.md) — for editors, publishers and approvers

The screens under **Site** in the sidebar (Pages, Site layout, Media library,
Import / Export), using the exact UI labels: a page's lifecycle from **New
page** to **Delete forever**, the approval workflow, scheduling, translations,
slugs and the redirects a rename leaves, the SEO tab, the header/footer nav
flags, the media library, snapshots, a tour of the block palette by category,
and what the Markdown block understands.

### [api-reference.md](api-reference.md) — for integrators

Every route under `/api/pagebuilder`: method, permission, request and response
shapes, and the error table. Also the public routes, the `PageDeleted`
event, the removed `public_claims` hook and the deprecated `url_prefix` keyword
of `render_public_page`.

### [operations.md](operations.md) — for operators

Installing and migrating, every setting (all database-backed, none read from the
environment, several needing a restart), turning on more languages, tenancy on a
single- and multi-tenant host, caching, ETags and the Content-Security-Policy on
public pages, the scheduler, storage on disk, and a troubleshooting table that
starts from the symptom.

### [architecture.md](architecture.md) — for maintainers

The tables, how a request binds a tenant, why boot-time settings are read in
`on_startup`, the status machine as a table, how the public viewer assembles a
page (claims, redirects, nav, ETag), how snapshots are captured and applied, the
frontend's block registry and i18n, and the contributor rules: the 300-line cap
and what may live under `pagebuilder/pages/`.

### [bundle-format.md](bundle-format.md) — the snapshot `.zip`

The bundle's layout, the versioned manifest (`format_version`, `contents`),
which versions this build reads, how an unknown one is refused, and how another
module could add a section later.

## The module in one paragraph

A page is one row with a `draft_data` and a `published_data` Puck document.
Editing writes the draft; **Publish** (or **Approve** after **Submit for
review**) copies the draft to the published copy and writes a revision. A page
is written in exactly one language for its lifetime; a translation is a sibling
page sharing a `translation_group`, with its own slug, draft and workflow. Slugs
are unique per tenant and language, and a rename records a redirect from the old
slug. Deleting moves a page to the trash for 30 days; purging removes it and
announces `PageDeleted`. Every table is tenant-owned, and every entry point binds
a tenant before it reads anything. Settings live in the database and are edited
on the Settings screen; the ones that decide routes need a restart.
