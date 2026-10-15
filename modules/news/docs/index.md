# News documentation

`simple_module_news` is a self-contained news archive for SimpleModule hosts.
Editors write **articles** in the module's own block editor, group them by
**category** and **tag**, take them through an optional review step, and
publish them to a public archive at `/news/` with its own article pages,
category, tag and author pages, an RSS feed and a sitemap. No other content
module is required; where the host also runs `simple_module_pagebuilder`, two
extras appear (a **News feed** block and Pages/Media sections in admin search).

Start with the document that matches what you are trying to do.

## Who should read what

| You are | Read |
|---|---|
| An editor or author writing, reviewing and publishing articles | [user-guide.md](user-guide.md) |
| A developer calling the news API, or building a feed of articles | [api-reference.md](api-reference.md) |
| An operator installing it, configuring it, or answering "why isn't this article showing?" | [operations.md](operations.md) |
| A developer changing the module | [architecture.md](architecture.md) |

### [user-guide.md](user-guide.md) — for editors and authors

The admin screens (Articles, the article screen, the body canvas, Categories,
Trash and Search everything) using the exact UI labels: what each field
means, how the review and schedule controls work, what the trash keeps, how a
translation is started, and what a reader sees at `/news/`.

### [api-reference.md](api-reference.md) — for integrators

Every route under `/api/news`, plus the admin screens and the public reader
routes: method, permission, request and response shapes, which reads are
anonymous, and the error responses.

### [operations.md](operations.md) — for operators

Installing and migrating, the optional `pagebuilder` extra and why it carries
a version floor, every setting (stored in the database, never read from the
environment), the scheduler under several replicas, multi-tenant hosts, and a
troubleshooting table that starts from the symptom.

### [architecture.md](architecture.md) — for maintainers

The five tables, the draft/published split, the workflow as a table, how
scheduling claims rows, how tenancy is bound at every entry point, the single
seam to pagebuilder, and a file map.

## The module in one paragraph

An article is one row in `news_articles` that owns its headline, slug, body,
status, SEO fields and language. Editors save into `draft_data`; publishing
copies it into `published_data`, which is the only thing the public viewer
serves, so a live article can keep being edited without readers seeing the
changes. Three permissions split the work: `news.view` sees the list,
`news.edit` writes and submits for review, `news.publish` publishes, schedules
and deletes for good. Every status change writes a revision. Binned articles
go to a trash that keeps their URL claimed. An article's language is fixed for
its lifetime; another language is a sibling article sharing a
`translation_group`, served under a `/{locale}` prefix. Settings live in the
database and are edited on the Settings screen. Every request is bound to a
tenant, so the module works on single- and multi-tenant hosts alike.
