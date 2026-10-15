# News API reference

All `/api/news` routes are JSON. Writes (`POST`/`PUT`/`DELETE`) need the
session's CSRF token in an `X-CSRF-Token` header; the console's own client
reads it from the `news_csrf` cookie. Errors are `{"detail": "<message>"}`
(validation errors use FastAPI's 422 list). Every route is bound to a tenant
first — see [Tenancy](#tenancy).

## Permissions

| Permission | Grants |
|---|---|
| `news.view` | the admin article list screen |
| `news.edit` | every write below except those also marked `news.publish`; the taxonomy, search, body and revision routes; draft visibility in listings |
| `news.publish` | publish, unpublish, schedule, approve, reject, hard delete, purge — always **in addition to** `news.edit` |

An administrator resolving to the wildcard permission counts as holding all
three.

## Reading articles — anonymous

`GET /api/news/articles` and `GET /api/news/categories` (and anything under
those two prefixes, `GET` only) are open to anonymous callers, because the
**News feed** block runs on public pages. A caller without `news.edit` sees
**published** articles only, whatever filter they send.

### `GET /api/news/articles`

| Query | Default | Meaning |
|---|---|---|
| `limit` | 20 | 1–100 |
| `offset` | 0 | |
| `category` | — | category name or slug |
| `tag` | — | tag slug or name |
| `q` | — | matches headline, slug, summary (excerpt) and tags — not the body |
| `status` | — | `draft`, `published` or `undated` (no display date). Ignored for non-editors. |
| `in_feed` | `false` | only articles with `show_in_feed` on |
| `undated_first` | `false` | undated before dated (the admin list's order) |
| `trashed` | `false` | the trash instead; empty for non-editors |
| `locale` | — | one language; an unconfigured value is ignored, a blank one returns nothing |
| `translation_group` | — | one article and its translations; blank returns nothing |

Order: pinned first, then newest display date, undated last (or first with
`undated_first`), then id. Response:

```json
{
  "items": [{
    "id": 7, "slug": "budget", "title": "Budget approved",
    "excerpt": "…", "cover_image_url": "https://…", "category": "Council",
    "tags": ["finance"], "pinned": false, "show_in_feed": true,
    "author": "A. Subash", "published_at": "2026-02-01T00:00:00Z",
    "locale": "en", "translation_group": "3f2c…", "updated_at": "…",
    "status": "published", "has_unpublished_changes": false,
    "url": "/news/budget", "edit_url": "/admin/news/articles/7/body"
  }],
  "total": 1,
  "counts": {"all": 1, "draft": 0, "published": 1, "undated": 0}
}
```

`excerpt` is the article's `meta_description` and `cover_image_url` its
`og_image`. `url` carries the language prefix (`/de/news/…`) for non-default
languages. `status` is `draft`, `submitted_for_review` or `published`.
`has_unpublished_changes` is only ever true for an editor. `counts` is scoped
by `q` and `category` but not by `status`.

Anonymous responses carry `Cache-Control: public, max-age=60`; an editor's
`private, no-store`. Both `Vary: Cookie` (plus the tenant header on a
multi-tenant host).

### `GET /api/news/categories`

`{"items": [{"category": "Council", "count": 4}]}` — counts of published
articles per category (drafts included for editors).

### `GET /api/news/articles/{id}/tags`

`["finance", "budget"]`. Same visibility rule as the listing: an unpublished
article is a 404 to a non-editor.

## Writing articles — `news.edit`

| Method & path | Body | Returns |
|---|---|---|
| `POST /articles` | `ArticleCreate` | `ArticleRead`, 201 |
| `PUT /articles/{id}` | `ArticleUpdate` (partial) | `ArticleRead` |
| `PUT /articles/{id}/tags` | `{"tags": ["a", "b"]}` (full replacement) | the tag names |
| `POST /articles/{id}/translations` | `ArticleTranslationCreate` | `ArticleRead`, 201 |
| `GET /articles/{id}/detail` | — | `ArticleDetail` |
| `PUT /articles/{id}/body` | `{"draft_data": {…}, "expected_updated_at"?}` | `ArticleDetail` |
| `GET /articles/{id}/revisions` | — | `RevisionRead[]`, newest first |
| `POST /articles/{id}/revisions/{rev}/restore` | — | `ArticleDetail` |
| `POST /articles/{id}/submit` | — | `ArticleRead` |
| `POST /articles/{id}/trash` | — | 204 |
| `POST /articles/{id}/restore` | — | `ArticleRead` |

**`ArticleCreate`** — `{"title", "slug"?, "locale"?, "category"?, "published_at"?,
"author"?}`. `title` 1–300 chars, required. `slug` matches `^[a-z0-9][a-z0-9-]*$`
(max 200); omitted, one is derived from the title and the first free variant
(`-2`, `-3`, … up to 20 tries) taken; supplied, it is used verbatim and a clash
is 409. `locale` omitted means the site default; an unconfigured one is 422.
The article starts as a `draft` in its own translation group.

**`ArticleUpdate`** — any of `title`, `slug`, `category`, `published_at`,
`pinned`, `show_in_feed`, `author`, `meta_description`, `og_image`,
`canonical_url`, `index_in_search`, `json_ld`, plus `expected_updated_at`.
Only fields sent are applied. `published_at: null` undates the article;
`title`, `slug` and `index_in_search` refuse `null`. `canonical_url` must be an
absolute `http(s)` URL; `og_image` that or a path starting with `/`; `""`
clears either. A changed `slug` records a redirect from the old one, in the
article's language. There is no `locale` field: a language is fixed.

`published_at` is a **display date**: the calendar day as sent is stored as
midnight UTC (`2026-02-01T23:00:00-06:00` records the 1st).

**`expected_updated_at`** — send the `updated_at` you loaded; if the stored
one differs the write is refused with 409 "This article was changed somewhere
else…". Omitted, the write goes through.

**`ArticleTranslationCreate`** — `{"locale", "slug"?, "title"?}`. Creates a
draft sibling in the same `translation_group`, copying category, author,
display date, `pinned` and `show_in_feed`. `slug` defaults to the source's own
(or the next free variant in that language); `title` to the source's headline.

**`ArticleDetail`** — `ArticleRead` plus `draft_data`, `has_published`,
`meta_description`, `og_image`, `canonical_url`, `index_in_search`, `json_ld`,
`rejection_note`, `publish_at`, `unpublish_at`.

**`PUT /body`** autosaves the block document into `draft_data` only: it cannot
change the slug, the status or the published snapshot.

**`RevisionRead`** — `{"id", "article_id", "title", "event", "note",
"created_at", "created_by"}`; `event` is `publish`, `unpublish`, `submit`,
`approve` or `reject`. Restoring copies the revision's body, title, summary
and image into the draft and does not publish.

**Trash** keeps the slug claimed. **Restore** leaves the status as it was and
clears any schedule time that elapsed while trashed.

## Publishing — `news.edit` + `news.publish`

| Method & path | Body | Effect |
|---|---|---|
| `POST /articles/{id}/publish` | — | copies `draft_data` to the published snapshot; status `published` |
| `POST /articles/{id}/unpublish` | — | status `draft`; clears both schedule times |
| `POST /articles/{id}/approve` | — | `submitted_for_review` → `published` in one step |
| `POST /articles/{id}/reject` | `{"note"?}` (≤ 2000) | `submitted_for_review` → `draft`, stores the note |
| `POST /articles/{id}/schedule` | `{"publish_at"?, "unpublish_at"?}` | sets/clears the times |
| `DELETE /articles/{id}` | — | 204; deletes the article outright |
| `DELETE /articles/{id}/purge` | — | 204; deletes a **trashed** article with its tags and redirects |

All but the two deletes return `ArticleRead`. Schedule fields are
three-valued: omitted leaves the time alone, an instant sets it (stored in
UTC), `null` cancels it. `publish_at` must be strictly before `unpublish_at`
(422). Scheduling changes no status; the scheduler does when the time comes.

## Categories and tags — `news.edit`

Under `/api/news/taxonomy` (deliberately not under the anonymous
`/categories` prefix, so draft counts stay private).

| Method & path | Body | Returns |
|---|---|---|
| `GET /taxonomy/categories` | — | `{"items": [CategoryRead]}` |
| `POST /taxonomy/categories` | `{"name", "slug"?}` | `CategoryRead`, 201 |
| `PUT /taxonomy/categories/{id}` | `{"name"?, "slug"?}` | `CategoryRead` |
| `POST /taxonomy/categories/reorder` | `{"ordered_ids": [3, 1, 2]}` | 204 |
| `DELETE /taxonomy/categories/{id}?reassign_to=<name>` | — | `{"reassigned": n}` |
| `GET /taxonomy/tags` | — | `{"items": [TagRead]}` |
| `POST /taxonomy/tags` | `{"name"}` | `TagRead`, 201 (find-or-create) |
| `PUT /taxonomy/tags/{id}` | `{"name"}` | `TagRead` |
| `POST /taxonomy/tags/{id}/merge` | `{"source_id"}` | `{"moved": n}`; the source tag is removed |
| `DELETE /taxonomy/tags/{id}` | — | 204; articles keep everything else |

`CategoryRead` is `{"id", "name", "slug", "position", "article_count",
"is_system"}`; `id` is 0 for the system **Uncategorised** row and for a
category that exists only as text on articles. Category names ≤ 80 chars, tag
names ≤ 60. Renaming a category rewrites the articles carrying the old name.
Deleting moves its articles to `reassign_to` (empty = Uncategorised); it
never deletes an article. `TagRead` is `{"id", "name", "slug",
"article_count"}`.

## Admin search — `news.edit`

`GET /api/news/search?q=…&per_section=5` (1–50). Empty `q` returns nothing.

```json
{"query": "canopy",
 "articles": [{"id": 7, "title": "…", "subtitle": "Council · draft",
               "url": "/admin/news/articles/7/edit", "excerpt": "…canopy…"}],
 "pages": [], "media": [],
 "article_total": 1, "page_total": 0, "media_total": 0,
 "pages_more_url": "", "media_more_url": ""}
```

Articles match on headline, slug, category, summary, draft body and tags.
`pages`, `media` and the two `*_more_url` fields are filled only where
pagebuilder is installed.

## Admin screens (Inertia)

| Path | Permission |
|---|---|
| `GET /admin/news/` | `news.view` |
| `GET /admin/news/categories`, `/trash` | `news.edit` |
| `GET /admin/news/articles/{id}/edit`, `/body` | `news.edit` |
| `GET /admin/news/articles/{id}/preview` | `news.edit`; 404 (not 403) otherwise; `noindex`, `private, no-store` |
| `GET /admin/search` | `news.edit` |

## Public reader routes — anonymous

Mounted under `public_route_prefix` (default `/news`) for the default language,
and `/{locale}/news` for each other content language.

| Path | Serves |
|---|---|
| `GET /news/` | archive, 12 per page, `?page=` and `?q=` |
| `GET /news/category/{slug}`, `/tag/{slug}`, `/author/{slug}` | the archive narrowed; empty (not 404) for an unknown one |
| `GET /news/{slug}` | one published article; an old slug 301s to the new one |
| `GET /news/feed.xml` | RSS 2.0, newest 20 in-feed articles of that language |
| `GET /news/sitemap.xml` | one sitemap for every language (default prefix only) |
| `GET /{default}/news/{slug}` | 301 to `/news/{slug}` (multilingual sites only) |

Archives and the feed list only published articles with `show_in_feed` on. A
page past the end is 404; a search result page is `noindex,follow`. The
article page sends an `ETag`, `Cache-Control` from the settings,
`Content-Language`, and `Content-Security-Policy` when `public_csp` is set,
with `<title>`, description, `og:*`, `twitter:*`, canonical, `hreflang`,
`robots` and JSON-LD written into the server-rendered `<head>`.

## Tenancy

| Surface | Single-tenant host | Multi-tenant host, no tenant resolved |
|---|---|---|
| `/api/news/*`, `/admin/news/*`, `/admin/search` | runs in tenant `default` | **403 `tenant_required`** |
| public reader routes | runs in tenant `default` | 404 "Article not found" |

## Error messages

| Status | `detail` | Where |
|---|---|---|
| 403 | `tenant_required` | any admin/API route, multi-tenant host with no tenant |
| 404 | `Article not found.` / `Article not found` | unknown, trashed, or (to non-editors) unpublished article |
| 409 | `Slug already in use` | create, update, translation |
| 409 | `Could not derive a free URL from '…'. Set one explicitly.` | create without slug |
| 409 | `This article was changed somewhere else. Reload…` | stale `expected_updated_at` |
| 409 | `This article already has a {locale} translation (check the trash).` | translations |
| 409 | `Only a draft can be submitted for review.` | submit |
| 409 | `Only a submitted article can be approved.` / `…rejected.` | approve, reject |
| 409 | `Only a published article can be unpublished.` | unpublish |
| 409 | `Only a trashed article can be purged.` | purge |
| 422 | `'fr' is not a content locale. Configured: en, de.` | create, translations |
| 422 | `publish_at must be strictly before unpublish_at` | schedule |
| 422 | `An article needs a headline.` / NUL character refused | create, update |
| 409 | `Uncategorised is a system category and always exists.` | category create/rename |
| 409 | `A category named '…' already exists.` / `That address is already used by another category.` | categories |
| 422 | `The address needs at least one letter or number.` | category slug |
| 404 | `Cannot reassign to '…': no such category.` | category delete |
| 400 | `Cannot merge a tag into itself.` | tag merge |
| 404 | `Revision not found` / `Category not found.` / `Tag not found.` | |
