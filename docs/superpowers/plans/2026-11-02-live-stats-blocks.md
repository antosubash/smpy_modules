# Live stats blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three Puck blocks — `NewsStats`, `RecordStats`, `ImageStats` — that show live counts on public pages, each served by a public read endpoint in the module that owns the data.

**Architecture:** Each module adds one anonymous, tenant-bound `GET`+`HEAD` endpoint answering `{"value": int}` for one metric, and one block registered from its own `pagebuilder-blocks.ts` that fetches one value per item and renders pagebuilder's existing `StatsView`. Pagebuilder itself does not change.

**Tech Stack:** FastAPI + SQLAlchemy (async), pytest; React + Puck (`@puckeditor/core`), vitest; Playwright.

**Spec:** `docs/superpowers/specs/2026-11-02-live-stats-blocks-design.md`

## Global Constraints

- No file under `modules/pagebuilder/` changes. Blocks import `StatsView` and `StatsWidgetProps['surface']` from `@simple-module-py/pagebuilder/pagebuilder/components/widgets/stats-widget`, and only from the block's own component files (`pagebuilder-blocks.ts` and the files it imports).
- Block names: `NewsStats`, `RecordStats`, `ImageStats`. Palette categories: news `feeds`, records `data`, images `images`. Never `layout: true`.
- `items`: Puck array, `min: 1`, `max: 6`. `clampStatItems` runs in `resolveData` on `trigger === 'load'` only (the `NewsFeed` precedent) **and** at the top of every renderer, because `resolveData` never runs on an anonymous public page.
- Each item has `label: string`, `prefix: string`, `suffix: string`, `iconUrl?: string` plus its metric fields. Block-level props are `title`, `subtitle`, `surface: 'default'|'lime'|'cards'`.
- Value text is `prefix + new Intl.NumberFormat(pageLocale).format(value) + suffix`. While loading and on failure the value is `–` (U+2013).
- Endpoint body: `{"value": <number>}`. Counts are ints; a records `sum` is the exact sum. Display formatting uses `Intl.NumberFormat(pageLocale, { maximumFractionDigits: 2 })`.
- Every new UI string is a catalogue key, added to the module's `locales/en.json` **and** `locales/de.json`.
- 300-line cap per file; split by responsibility.
- Python test runs cap xdist at `PYTEST_WORKERS=8` / `-n 8`; never run two suites at once.
- No `biome-ignore` and no Biome config overrides; fix lint properly.
- Commits end with `Claude-Session: https://claude.ai/code/session_017uTbtobjCKQYnAxF5tgK8t`.

## Review Focus

1. A draft, trashed, embargo-expired or other-tenant row reaching any count. Each endpoint task has an exclusion test per case.
2. A records `sum` over a field the public shape does not expose, or a filter on a hidden column, must be refused (400), never answered. Task 3 tests both.
3. An images count must never include an image held back by redaction, or one in a private or internal collection, including in the all-collections total. Task 5 tests both.
4. A stored block whose items exceed 6, or name an unknown metric, must still render (clamped) rather than throw. The block tasks test `resolveData` on load.
5. The records `/{type_key}/stats` route must not be shadowed by `/{type_key}/{uuid}`, and a record whose slug is `stats` must still be readable. Task 3 tests the route order.

---

### Task 1: news stats endpoint

**Files:**
- Create: `modules/news/news/stats.py` (query), `modules/news/news/endpoints/api/stats.py` (route)
- Modify: `modules/news/news/endpoints/api/__init__.py` (include router), `modules/news/news/constants.py` (new `PUBLIC_STATS_PREFIX: Final = f"{ROUTE_PREFIX_API}/stats"`), `modules/news/news/module.py` (`register_public_routes` also adds `PUBLIC_STATS_PREFIX` with `methods={"GET", "HEAD"}`; `register_public_routes` hardcodes GET for the others, so a HEAD would otherwise still need a session)
- Test: `modules/news/tests/test_stats_api.py`

**Interfaces:**
- Produces: `GET /api/news/stats?metric=published&category=<name or slug>&locale=<tag>` and `HEAD` on the same path → `{"value": int}`. Without `locale` it counts all languages; without `category`, all categories.
- `async def count_published(db: AsyncSession, *, category: str | None, locale: str | None, now: datetime) -> int` in `news/stats.py`: `status == PUBLISHED`, `NOT_TRASHED`, `unpublish_at IS NULL OR unpublish_at > now`, plus `query_filters.locale` and the category equality.
- The route lives on news's existing API router (router-level `bind_admin`; anonymous GET via `PUBLIC_READ_PREFIXES`, the same path the `NewsFeed` reads take). Headers come from `_deps.cache(response, request, include_drafts=False)`. `metric` is a `Literal["published"]` query param, so anything else is a 422.

- [ ] **Step 1: Write failing tests** in `test_stats_api.py`, using the fixtures the existing news API tests use (`modules/news/tests/conftest.py`):
  - `test_counts_only_published_live_articles`: seed 2 published, 1 draft, 1 published+trashed, 1 published with `unpublish_at` in the past, and 1 with it in the future. Anonymous GET → `{"value": 3}`.
  - `test_category_and_locale_narrow`: published `en`/`a`, `en`/`b`, `de`/`a`. `?category=a` → 2; `?locale=de` → 1; both → 1.
  - `test_anonymous_cache_headers`: `Cache-Control == "public, max-age=60"`, `"Cookie" in Vary`.
  - `test_head_answers`: an anonymous HEAD through the real auth middleware (not a dependency override) → 200, empty body.
  - `test_unknown_metric_is_422`: `?metric=drafts` → 422.
  - `test_other_tenant_not_counted`: in multi-tenant mode, as in `test_tenancy_public.py`, an article in tenant B is not counted for tenant A.
  - `test_stats_prefix_is_public`: extend the assertion in `test_module.py:149` so `/api/news/stats` is registered for GET and HEAD, and the existing prefixes stay GET-only.
- [ ] **Step 2: Run** `uv run pytest modules/news/tests/test_stats_api.py -n 8 -q`. Expected: fails (404).
- [ ] **Step 3: Implement** `count_published` and the route. HEAD is explicit with `@router.api_route(..., methods=["GET", "HEAD"])`.
- [ ] **Step 4: Run** the same command, then `uv run pytest modules/news/tests/test_module.py -q`. Expected: pass.
- [ ] **Step 5: Docs.** Add a "Live stats block" paragraph to `modules/news/README.md` after the feed block section: the endpoint, the metric, and what counts.
- [ ] **Step 6: Commit** `feat(news): public article count for the stats block (#88)`.

### Task 2: `NewsStats` block

**Files:**
- Create: `modules/news/news/components/NewsStats.tsx` (config + render, ≤300 lines; move the render to `NewsStatsRender.tsx` if needed), `modules/news/news/components/NewsStats.test.tsx`
- Modify: `modules/news/news/utils/api.ts` (add `fetchPublishedCount`), `modules/news/news/pagebuilder-blocks.ts` (register `NewsStats` beside `NewsFeed`; extend the header comment's list of files allowed to import pagebuilder), `modules/news/news/locales/en.json` + `de.json` (`news.stats.*`)

**Interfaces:**
- Consumes: Task 1's endpoint.
- `fetchPublishedCount(opts: { category: string; locale: string | null; signal: AbortSignal }): Promise<number>`. It calls `GET ${BASE}/stats?metric=published[&category][&locale]` with `credentials: 'same-origin'`.
- Item: `{ language: 'page' | 'all'; category: string; label; prefix; suffix; iconUrl? }`. With `'page'` it sends `useContentLocale()`; with `'all'` it sends no locale.
- Exports `NewsStatsBlock: ComponentConfig<NewsStatsProps>`, `NewsStatsRender`, and `clampStatItems(items): Item[]`, which caps at 6 and drops items whose `language` is not `'page' | 'all'`.
- Keys under `news.stats`: `label`, `title`, `subtitle`, `surface`, `surface_default`, `surface_lime`, `surface_cards`, `items`, `item_label`, `item_prefix`, `item_suffix`, `item_icon`, `item_category`, `item_language`, `item_language_page`, `item_language_all`. `defaultProps`: `title: ''`, `subtitle: ''`, `surface: 'default'`, `items: [{ language: 'page', category: '', label: 'Articles published', prefix: '', suffix: '' }]`.

- [ ] **Step 1: Failing vitest** `NewsStats.test.tsx` (happy-dom, `fetch` stubbed as in `NewsFeed.test.tsx`):
  - `resolveData` on `load` clamps 8 items to 6 and drops `language: 'x'`; on `replace` it is unchanged.
  - Render shows `–` before the response; after `{value: 1284}` with page locale `de` it shows `1.284`; with prefix `~` and suffix `+` it shows `~1.284+`.
  - A rejected fetch shows `–`.
  - `language: 'all'` sends no `locale` param; `'page'` sends the page's locale.
  - Registration: importing `pagebuilder-blocks.ts` registers `NewsStats` in category `feeds`, and it is absent from the layout config.
- [ ] **Step 2: Run** `npx vitest run modules/news/news/components/NewsStats.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.** The icon field uses the same media picker the static Stats item uses. Import pagebuilder's `createImageField`/`mediaLibraryAdapter` the way the static widget does; if that import is not reachable, use a plain `text` URL field. One `useEffect` per block, keyed on the items' fetch inputs, runs every item's fetch under one `AbortController` with `Promise.allSettled`.
- [ ] **Step 4: Run** the vitest file, then `make lint` (biome, tsc, locales). Expected: PASS.
- [ ] **Step 5: Commit** `feat(news): NewsStats block (#88)`.

### Task 3: records stats endpoint

**Files:**
- Create: `modules/records/sm_records/services/public_stats.py`
- Modify: `modules/records/sm_records/endpoints/api/public.py` (route registered **before** `/{type_key}/{uuid}`; if the file passes 300 lines, move both `_read_route` stats handlers to `endpoints/api/public_stats.py` on the same router)
- Test: `modules/records/tests/test_public_stats.py`

**Interfaces:**
- Produces: `GET|HEAD {public_route_prefix}/{type_key}/stats?metric=count|sum:<field>&filter=…&locale=<tag>` → `{"value": int}`. Filters are parsed with the existing `parse_filters` dependency.
- `async def public_stat(db: AsyncSession, key: str, *, settings: RecordsSettings, metric: Metric, filters: Sequence[Filter], locale: str | None) -> int | float` in `services/public_stats.py`:
  - `get_public_type(db, key)` (shared 404 for a private or missing type);
  - `_check_columns(rtype, [*filters, Filter(field=metric.field)…], [])`, which refuses a summed field outside the public shape;
  - the locale is resolved exactly as `list_public_records` resolves it (an omitted locale → the configured default, case-normalised, an unsupported or removed language refused/empty the same way), and the narrowing is **always** `_narrow_for(record, resolved_locale)`, so a translated record counts once and a language no longer configured never counts;
  - the statement is `count(distinct record.id)`, or `sum` of the metric's index column, built with the same filter-joining helpers `aggregate_query` uses (`tables_for`, `_column`, `_check_metric`, the filter grammar). There is no `group_by` and no cap.
  - `min`/`max` metrics are refused with a `QueryError("metric", "bad_value", …)` → 400.
- Response headers through `_public_cache.apply` (ETag + `public_cache_seconds`); refusals through the existing `_refused` → 400 naming the field.

- [ ] **Step 1: Failing tests** in `test_public_stats.py`, with the fixtures of `test_public_records*.py`:
  - `test_count_published_only`: on a public type, 3 published, 1 draft, 1 trashed → 3.
  - `test_private_type_is_404`: same body as an unknown type.
  - `test_sum_public_number_field`: published indexed `area` values 1.25 and 2.5, plus a draft at 100 → `3.75`.
  - `test_sum_refuses_hidden_or_non_number`: a virtual or undeclared field → 400 naming it; a text field → 400.
  - `test_filter_narrows`: `filter=<a public field>:eq:x` counts only matches.
  - `test_hidden_filter_refused`: for both `count` and `sum`, a filter on a hidden fixed column (`created_at`, `position`) and on a provider-only virtual field → 400 naming the field.
  - `test_locale_narrows`: on a translatable type, `en` and `de` rows of one record give `?locale=de` → 1 and no locale → 1 (the default language), never 2.
  - `test_locale_resolution_matches_listing`: an unsupported locale, a removed one and an upper-case one answer exactly as `GET /{key}?locale=…` does (same status; same count as that listing's `total`).
  - `test_min_metric_refused`: `metric=min:area` → 400.
  - `test_stats_route_not_shadowed`: `/{key}/stats` returns the stats body, and a record with slug `stats` is still served by its uuid route.
  - `test_cache_and_head`: ETag present, `Cache-Control` per `test_public_cache.py`, HEAD 200.
  - `test_other_tenant_not_counted`: multi-tenant, as in the existing public tenancy tests.
- [ ] **Step 2: Run** `uv run pytest modules/records/tests/test_public_stats.py -n 8 -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it again, plus `uv run pytest modules/records/tests -k "public" -n 8 -q`. Expected: PASS.
- [ ] **Step 5: Docs.** Add the endpoint to the public API section of `modules/records/docs/` (the file documenting `/api/records/public`).
- [ ] **Step 6: Commit** `feat(records): public count/sum for the stats block (#88)`.

### Task 4: `RecordStats` block

**Files:**
- Create: `modules/records/sm_records/components/widget/RecordStatsBlock.tsx` (config), `RecordStatsRender.tsx` (render), `RecordStatsBlock.test.tsx`
- Modify: `modules/records/sm_records/utils/public-api.ts` (add `fetchPublicStat`), `modules/records/sm_records/pagebuilder-blocks.ts` (register in category `data`), `modules/records/sm_records/locales/en.json` + `de.json` (`records.stats.*`)

**Interfaces:**
- Consumes: Task 3's endpoint.
- `fetchPublicStat(prefix: string, typeKey: string, opts: { metric: string; filter: string; locale: string; tenant: string; signal: AbortSignal }): Promise<number>` follows `fetchPublicRecords`: same prefix default, tenant header, `credentials: 'omit'`.
- Block-level props, copied from `RecordsListBlock` with the same semantics: `locale`, `tenant`, `apiPrefix`.
- Item: `{ typeKey; metric: 'count' | 'sum'; field: string; filter: string; label; prefix; suffix; iconUrl? }`. `resolveFields` fills the `typeKey` options from the admin `listTypes()` as `RecordsList` does, and the `field` options from the chosen type's declared number fields **that are indexed** (an unindexed one is refused `not_indexed` by the endpoint). `field` is ignored for `count`.
- Exports `RecordStatsBlock`, `RecordStatsRender`, `clampStatItems`. The hidden-field helper is the existing local `hiddenField` pattern only if needed; prefer no hidden fields.
- Keys under `records.stats`: the same set as news plus `item_type`, `item_metric`, `item_metric_count`, `item_metric_sum`, `item_field`, `item_filter`, `locale`, `tenant`, `api_prefix`.

- [ ] **Step 1: Failing vitest**, the same cases as Task 2 adapted, plus: a `sum` item sends `metric=sum:<field>` and `3.75` renders as `3,75` under `de`; a `count` item ignores `field`; an item without `typeKey` shows `–` and makes no request; the field options list indexed number fields only (an unindexed number field and a text field are absent).
- [ ] **Step 2–4:** Run vitest (FAIL), implement, run vitest and `make lint` (PASS).
- [ ] **Step 5: Commit** `feat(records): RecordStats block (#88)`.

### Task 5: images stats endpoint

**Files:**
- Create: `modules/images/sm_images/web/services/public_stats.py`
- Modify: `modules/images/sm_images/web/endpoints/public.py` (add the route), `modules/images/sm_images/web/serving/cache.py` (add `stats_headers(request) -> str`)
- Test: `modules/images/tests/web/collections/test_public_stats.py`

**Interfaces:**
- Produces: `GET|HEAD /api/images/public/stats?metric=images|located|collections&collection=<slug>` → `{"value": int}` (`get_and_head(router, "/stats")`).
- `async def public_stat(db, *, metric: Literal["images","located","collections"], collection: Collection | None) -> int` in `web/services/public_stats.py`:
  - `collections`: count of `Collection` with `visibility == PUBLIC` (soft-delete and tenant filtered by the mixins). The `collection` argument is ignored.
  - `images`/`located`: `count(Image.id)` / `count(Image.lat)` with `Image.is_deleted.is_(False)` and `redaction.ready_clause(c)`, for the one collection, or summed over every public collection.
  - Counts exactly the images `public_gallery.page` would list: not trashed, `redaction.ready_clause(c)`, **and** a current `small` rendition (`source_generation == Image.display_generation`). Extract the gallery's visibility predicate into one helper in `web/services/public_gallery.py` (e.g. `visible_clause(collection)`) used by both the gallery and the stats; do not copy it.
- `collection` resolves through `public_collection` semantics (a private, internal, trashed or unknown slug → the usual 404), raised as the module's `ImagesError` so `PublicRoute` adds `no-store`. `metric` is a plain `str` query param validated in the handler and refused with an `ImagesError` (400), not a `Literal` (FastAPI's 422 would bypass `PublicRoute` and its `no-store`). No ETag: the body is a few bytes.
- Headers: with a collection, `cache.cache_headers(request, collection, cache.DISPLAY, twin=True)`; without, `cache.stats_headers(request)`, which is `PUBLIC_NO_CACHE` when `_shared_tenant(request)` and otherwise `PRIVATE`.

- [ ] **Step 1: Failing tests**, with the fixtures of `test_gallery_api.py`:
  - `test_counts_public_ready_images`: a public collection with 3 ready images, 1 trashed, 1 held back by redaction, 1 with no `small` rendition and 1 whose rendition is stale (set up as the gallery tests do) → `images` 3, for the collection and in the all-collections total. With 2 of them located → `located` 2.
  - `test_all_collections_total_excludes_private`: two public and one private collection → the sum covers only the public two. `collections` → 2, and a trashed public collection is not counted.
  - `test_private_slug_is_404_no_store`.
  - `test_unknown_metric_is_400_no_store`.
  - `test_cache_headers`: a single collection and the total → `public, no-cache` only in single-tenant mode with no request-chosen tenant. Both are `private, no-cache` when the tenant came from upstream (`request.state.tenant_id`), from an explicitly selected `"default"`, from a bound `tenant_context`, or in multi-tenant mode. Multi-tenant with no tenant resolved → 404 `no-store`.
  - `test_head_answers`.
  - `test_other_tenant_not_counted`.
  - `test_viewer_fields_unchanged`: the existing viewer_stats tests still pass after the helper move.
- [ ] **Step 2–4:** Run `uv run pytest modules/images/tests/web -n 8 -q -k "stats or gallery or viewer"` (FAIL), implement, re-run (PASS).
- [ ] **Step 5: Docs.** Add the endpoint to the public API part of `modules/images/docs/` (where `/api/images/public/c/{slug}/images` is documented).
- [ ] **Step 6: Commit** `feat(images): public counts for the stats block (#88)`.

### Task 6: `ImageStats` block

**Files:**
- Create: `modules/images/sm_images/ui/components/block/ImageStatsBlock.tsx`, `ImageStatsRender.tsx`, `ImageStatsBlock.test.tsx`
- Modify: `modules/images/sm_images/ui/utils/api-public.ts` (add `fetchPublicStat`), `modules/images/sm_images/pagebuilder-blocks.ts` (register in category `images`), `modules/images/sm_images/locales/en.json` + `de.json` (`images.stats.*`), `modules/images/sm_images/ui/page-tests/pagebuilder-blocks.test.ts` (expects `ImageStats`)

**Interfaces:**
- Consumes: Task 5's endpoint.
- `fetchPublicStat(opts: { metric: 'images'|'located'|'collections'; collection: string; signal: AbortSignal }): Promise<number>`.
- Item: `{ metric; collection: string; label; prefix; suffix; iconUrl? }`. `resolveFields` fills the `collection` options by paging admin `listCollections('public', cursor)` as `ImageGalleryBlock` does, with an "All public collections" option whose value is `''`. `collection` is ignored for `collections`.
- Keys under `images.stats`: the shared set plus `item_metric`, `item_metric_images`, `item_metric_located`, `item_metric_collections`, `item_collection`, `item_collection_all`.

- [ ] **Step 1: Failing vitest**, the same cases as Task 2 adapted, plus: a `collections` item sends no `collection` param.
- [ ] **Step 2–4:** Run vitest (FAIL), implement, run vitest and `make lint` (PASS).
- [ ] **Step 5: Commit** `feat(images): ImageStats block (#88)`.

### Task 7: e2e specs

**Files:**
- Create: `tests/e2e/news-stats.spec.ts`, `tests/e2e/records-stats.spec.ts`, `tests/e2e/images-stats.spec.ts`. Each stands alone and seeds its own data, following `news-feed.spec.ts`, `records-widget.spec.ts`, and the images upload specs.

Each spec covers:
- the block is offered in the page palette and absent from the site-layout palette;
- an anonymous visitor sees the live number on a published page (seeded through the API, the page published with the block's stored data);
- the number changes after a mutation: publish one more article; publish one more record; upload one more image to a public collection, with the e2e server's tasks running eagerly;
- something not public is not counted: a draft article; a record of a private type (`–`, since that is a 404); a private collection's images left out of the all-collections total.

- [ ] **Step 1:** Write the three specs.
- [ ] **Step 2: Run** each alone, after `~/.claude/bin/wait-for-headroom`: `npx playwright test tests/e2e/news-stats.spec.ts`, and the same for the other two. Expected: PASS.
- [ ] **Step 3: Commit** `test(e2e): live stats blocks (#88)`.

## Order and parallelism

Tasks 1, 3 and 5 touch disjoint modules and may run two at a time. Each block task needs its endpoint task first (2 after 1, 4 after 3, 6 after 5). Task 7 runs last and alone. Task 3 is the hard one (the metric query without `group_by`, and route order); give it to opus.
