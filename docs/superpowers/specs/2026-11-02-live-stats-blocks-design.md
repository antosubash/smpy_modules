# Live stats blocks (#88)

## Goal & scope

Page authors can place a stats band whose numbers come from live data instead of
typed-in text: "1,284 articles published", "312 sites recorded", "48,900 photos".
Each block lives in the module that owns the data and registers itself from that
module's `pagebuilder-blocks.ts` (user direction): pagebuilder gains nothing but
an unchanged, reused view.

In:

- `NewsStats` (news), `RecordStats` (records), `ImageStats` (images): one Puck
  block per module, each with up to 6 stat items.
- One public, anonymous, tenant-bound read endpoint per module that answers one
  number per item, counting only what that module's public pages already show.
- Number formatting in the page's language, an optional prefix/suffix per item.

Out: charts or time series, a block mixing modules, totals across tenants,
anything an anonymous visitor could not already see on a public page.
Form submission (#101) and live news (`NewsFeed`) are already done.

## Approach

Each block reuses pagebuilder's exported presentational `StatsView`
(`components/widgets/stats-widget.tsx`, title/subtitle/items/surface), imported by
deep path from `pagebuilder-blocks.ts`'s component the way `NewsFeed` imports
`article-cards-render`. The three live blocks therefore look identical to the
static `Stats` block, with the same three surfaces.

Rejected:

- **One generic "Live stats" block in pagebuilder with a data-source registry.**
  The user wants the widgets in their own modules; it would also make pagebuilder
  know about every module's metrics.
- **Reuse the admin aggregate/list endpoints from the browser.** They are
  permission-gated (records aggregate) or count drafts (news category counts),
  and an anonymous page cannot call them.

## Design

### Shared block shape (each module)

```ts
type StatItem = { metric: <module metric>; /* metric args */; label: string;
                  prefix: string; suffix: string; iconUrl?: string };
type Props = { title; subtitle; surface: 'default'|'lime'|'cards'; items: StatItem[] };
```

- `items` is a Puck array, `min: 1`, `max: 6`. `resolveData` on `load` drops
  items past 6 and unknown metrics, like `NewsFeed`'s load-only clamp.
- Render: one `GET` per item in `useEffect` with an `AbortController`, values
  formatted with `Intl.NumberFormat(pageLocale)` and passed to `StatsView` as
  `prefix + number + suffix`. While loading, and for an item whose request failed,
  the value is `–`, so the band keeps its layout. The editor shows the same live
  numbers.
- Block names are unique (`NewsStats`, `RecordStats`, `ImageStats`); `Stats` is
  pagebuilder's built-in. Palette categories are the module's existing ones
  (news `feeds`, records `data`, images `images`). Not offered in the site layout
  palette.
- Labels are catalogue keys (`keys.<module>.stats.*`) in `en.json` and `de.json`.

### Metrics and endpoints

Every endpoint is `GET` + explicit `HEAD`, under the module's own `bind_public`
(single-tenant host: `"default"`; multi-tenant: the resolved tenant; none: 404),
auth-exempt for `GET`, answers `{"value": <int>}`, and uses the module's existing
public cache helper. Every refusal (unknown type, private collection, bad metric)
is the module's usual public 404/400, with `no-store`.

**news** — `GET /api/news/stats?metric=published&category=&locale=`

| metric | counts |
|---|---|
| `published` | articles with `status = published`, not trashed, and `unpublish_at` null or in the future |

- `category`: optional, one category, by name or slug (the listing's rule).
- `locale`: an item field, either "this page's language" (the default) or "all
  languages".
- Served from news's API router like the `NewsFeed` reads it sits beside: the
  router's `bind_admin` (a multi-tenant host with no tenant gives 403
  `tenant_required`), opened to anonymous `GET` through `PUBLIC_READ_PREFIXES`,
  and cached with `_deps.cache` (`PUBLIC_CACHE_CONTROL`, 60 s, `Vary: Cookie`
  plus `vary_on_tenant`).

**records** — `GET {public_route_prefix}/{type_key}/stats?metric=count|sum:<field>&filter=`

| metric | counts |
|---|---|
| `count` | published, non-trashed records of a type with `is_public` |
| `sum:<field>` | sum of a number field that the type's public shape exposes |

- Goes through the existing public gates: `get_public_type` (a private type is
  the shared 404), `_published_only`, and `_check_columns` for the filter and
  the summed field. It reuses `aggregate_query` with those clauses added.
- A sum over a non-integer field is rounded for display only (two decimals);
  the API returns the exact number. Only indexed number fields can be summed.
- The locale is resolved as the public listing resolves it and always applied,
  so a translated record counts once.
- The item picks a type from the admin type list (`resolveFields`, as
  `RecordsList` does) and offers only that type's public number fields for
  `sum`.
- Cached with `_public_cache.apply` (ETag, `public_cache_seconds`).

**images** — `GET /api/images/public/stats?metric=images|located|collections&collection=<slug>`

| metric | counts |
|---|---|
| `images` | images the public gallery would show: not trashed, passing `redaction.ready_clause`, with a current `small` rendition (the gallery's own predicate, shared) |
| `located` | the same, with a location |
| `collections` | public, non-trashed collections (no `collection` argument) |

- `collection` is optional. Without it, `images` and `located` are summed over
  every public collection; with it, the slug must be public or the answer is
  the usual 404.
- It never reads the stored `Collection.image_count`, which includes images the
  public must not see.
- Cached with `cache.stats_headers` (`cache.cache_headers`'s tenant rule: `PUBLIC_NO_CACHE` for a shared
  tenant source, else `PRIVATE`); no ETag, the body is a few bytes.

### Permissions

None on the reads: they expose only what the module's public pages already show.
Picking a type or collection in the editor uses the admin lists the existing
blocks already use.

## Decisions made (override any at approval)

1. One PR for all three blocks. The work is the same pattern three times, and
   QA can compare them on one page.
2. Up to 6 items per block, one request per item. A batch endpoint would save
   round trips but would lose per-number HTTP caching; 6 small cached GETs are
   fine.
3. News counts check `unpublish_at` at read time, so an expired embargo
   disappears from the number immediately rather than at the next scheduler
   tick.
4. No byte or area metrics for images: the public page shows neither, and file
   sizes say something about originals.
5. A failed item shows `–` instead of hiding the block. A missing number reads
   as "not available"; a vanished section reads as broken.
6. No server-side cache beyond HTTP caching. Each count is one indexed,
   tenant-scoped query.

## Testing

- **Python, per module:** the endpoint counts only public, published,
  non-trashed rows. Each test seeds a draft, a trashed row, a private type or
  collection, and an image held back by redaction, and asserts it is excluded.
  Also: tenancy (multi-tenant with no tenant gives 404; another tenant's rows
  are never counted), cache headers on success and `no-store` on errors, `HEAD`,
  an unknown metric or field gives 400, and a `sum` over a field outside the
  public shape is refused.
- **Vitest, per block:** the `resolveData` load clamp (6 items, unknown metric
  dropped), formatting (locale, prefix/suffix), `–` while loading and on
  failure, and the registration names and categories.
- **E2E, one self-contained spec per module** (`news-stats`, `records-stats`,
  `images-stats`): offered in the palette and absent from the layout palette;
  an anonymous visitor sees the live number on a published page; publishing,
  trashing or adding a row changes it.
- **QA in the browser:** add all three to one page, try each surface, switch
  the page language (number format), and as an anonymous visitor confirm that
  drafts, private types and private collections are never counted.

## Risks

- `StatsView` pulls in a little more of pagebuilder (`fields`, `i18n`) through
  its module. That is the same accepted coupling as `NewsFeed` → `article-cards-render`,
  confined to the block files.
- `aggregate_query`'s `sum` needs an indexed number field. If a public number
  field is not indexed, the item editor will not offer it for `sum`, rather
  than the block failing at render.
