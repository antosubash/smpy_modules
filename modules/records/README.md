# simple_module_records

Generic structured content for SimpleModule hosts: an administrator defines
**Record Types** — arbitrary named schemas, each an ordered list of typed
field definitions — from the admin UI, and performs full CRUD on their
**Records**, without a developer writing a module, a SQLModel table, or an
Alembic migration for each one.

The storage shape follows [YesSql](https://github.com/sebastienros/yessql) and
the content layer Orchard Core builds on it: every record of every type is a
row in one document table with its field values in a `JSON` column, and a
declared field is projected into a separate, typed, real SQL index table so
it stays genuinely queryable. See `docs/plans/2026-09-19-records-module-design.md`
in the source repo for the full design.

## Documentation

The rest of this file is the long-form reference. Start with
[`docs/index.md`](docs/index.md), which says who should read what.

- [`docs/user-guide.md`](docs/user-guide.md) — for administrators: every admin
  screen in the order you meet it, with the exact UI labels.
- [`docs/api-reference.md`](docs/api-reference.md) — every endpoint, the query
  grammar, the wire shapes, the error table and the file formats.
- [`docs/operations.md`](docs/operations.md) — install, migrations, settings,
  the CLI, health checks and the deployment constraints.
- [`docs/architecture.md`](docs/architecture.md) — for contributors: the
  document/index split, the schema-change pipeline and the extension points.
- [`docs/performance.md`](docs/performance.md) — what it costs at scale, and
  how to measure it yourself.

## Install

```bash
pip install simple_module_records
```

Add `simple_module_records` to your host's dependencies; for an in-repo
checkout, resolve it from the workspace:

```toml
dependencies = ["simple_module_records"]

[tool.uv.sources.simple_module_records]
workspace = true
```

Then run `make migration msg="add records"` and apply it with `make migrate`.
The module's first revision is labelled `records`. Note that
`alembic downgrade records@base` does **not** remove only this module: the
revision chains off your host's current head, so that command rolls back
every revision beneath it as well. To drop this module's tables alone,
downgrade to the revision *before* the records one, or drop the eleven
`records_*` tables directly (plus the eight `records_c_<name>_*` tables of
each collection your host declares).

## Usage

Go to **Records** in the admin sidebar (`/admin/records`) to define a
type and its fields; a type that opts in gets its own entry there too. Each type gets a generic, schema-driven list screen and
form at `/admin/records/{key}` and `/admin/records/{key}/{uuid}` — one pair of
screens serves every type; nothing is generated per type.

The same operations are available as a JSON API under `/api/records`. Every
route on it requires a session and one of the three permissions below. A type
marked **`is_public`** additionally serves its *published* records to callers
with no session at all, under `public_route_prefix` — see
[Public read API](#public-read-api).

**If a field is not indexed, it is not queryable.** `data` is opaque storage;
no endpoint filters, sorts, or searches by extracting from it. A field must
be marked `indexed: true` on its type to be usable as a filter or sort key —
this is a deliberate hard rule, not a v1 limitation, and it is what keeps
performance a property of the schema rather than a cliff discovered under
load.

### Sidebar entries

Every type is reachable through the **Record Types** entry above. A type can
also ask for an entry of its own, next to it: turn on **Show in sidebar** in
the type editor (`show_in_menu` on the API) and the admin sidebar gains an
item in its own *Records* group — right after *Content*, where the hub entry
itself lives — labelled with the type's plural, using the type's icon and
linking to its record list. The type gets its own group rather than joining
*Content* as a peer of pagebuilder's "Pages" or news' "Articles": nothing
would otherwise say the entry is a record type, and a type named "Pages"
would be ambiguous with pagebuilder's own. Off by default — a sidebar with an
item per type is unusable on an install with thirty of them — and the hub
entry stays whatever you do.

It is **not a schema change**: no classification, no dry run, no revision and
no `schema_version` bump, exactly like `is_public`. It round-trips through
export and import with the rest of the definition.

A type's `allowed_roles` narrow who sees the entry, deliberately: role
filtering in the menu is a plain intersection with no admin bypass, and so is
the check on the record list behind the link, so a caller the type excludes
would get a 403 from a link only they could see. An empty `allowed_roles` —
the default — means everyone with `records.view` sees it.

**The entry can lag by `menu_refresh_seconds` in a multi-worker host.** The
framework's menu registry is built once per process, at boot, and types are
created long after that; the worker that served your save re-reads the types
on its next page request, and the others within the window (5 seconds by
default, `0` to re-read on every page request). Nothing about the record data
is affected — only which links the sidebar is showing.

### Paging a large type

`GET /api/records/types/{key}/records` takes `?page=` and `?page_size=` as it
always has, and three parameters that exist because none of the above scales
past a type of a few thousand records. The same three are available on the
public read API.

| parameter | does |
|---|---|
| `?after=<cursor>` | returns the page *after* the row a previous page's `next_cursor` names, with no `OFFSET` |
| `?total=false` | skips the count query entirely: `total` comes back `null` |
| — | `total` is exact up to `max_count`; beyond it `total` is `max_count` and `total_capped` is `true` |

A page reads back as
`{items, total, total_capped, page, page_size, next_cursor}`.

**The grammar is bounded too.** `?filter=` is capped at `max_filter_terms`
(20) and an `in:` list at `max_in_values` (200); `?sort=` is deduplicated by
field — a repeated term cannot change an order the first one fixed — and then
capped at `max_sort_terms` (5) distinct fields. Over any of them is a `400`
naming the parameter, on the admin listing, the export and the anonymous API
alike: every term is another `EXISTS` or another `LEFT JOIN`, and unbounded
they were a `500` rather than a slow page. `?page=` is bounded at 1,000,000 —
an `OFFSET` past `max_count` has nothing left to find, and `?after=` is what
walks a type that large.

**The count is bounded.** A page can stop after `page_size` matches; the
`COUNT` behind `total` never can, so a filter matching most of a large type
paid for all of it on every page of it. `total` is now exact up to `max_count`
(10,000 by default) and reported as that ceiling with `total_capped: true`
beyond it — the admin list renders that as "10,000+". A caller that does not
render the number should send `?total=false` and skip the statement.

**`?after=` is keyset pagination.** Read `next_cursor` off a page and send it
as `?after=` to get the next one; `null` means there are no more. The cost of
page 200 is then the cost of page 1, which `?page=200` is not — `OFFSET`
produces and discards everything before the page it wants. Walking a whole
type looks like:

```python
url = "/api/records/types/order/records?page_size=200&sort=-placed_at&total=false"
while url:
    page = client.get(url).json()
    handle(page["items"])
    cursor = page["next_cursor"]
    url = f"...&after={cursor}" if cursor else None
```

The cursor is opaque (base64 of the row's sort values and its id) but not
secret, and it carries a digest of the sort it was produced under. That digest
covers everything that changes what the value tuple *means*: the type, the
ordered `(field, direction)` list, whether the listing was the trash, **the
index kind behind each sort field** (so a field retyped from `number` to `text`
mid-walk invalidates the cursor instead of comparing a decimal against a
string) and, on the public API, **the `?locale=` the listing was narrowed to**.
Three things are a `400`: a cursor that does not decode, a cursor replayed
under a different sort — in any of those senses — or against the trash, and
`?page=` and `?after=` sent together, which are two ways of asking for a page
and the server will not guess which one you meant. `?page=` stays for the admin
UI, which shows numbered pages.

A full final page still returns a `next_cursor`; the request after it comes
back empty with `next_cursor: null`. That is one extra round trip at the end
of a walk and is the ordinary contract of cursor pagination — "fewer rows than
asked for" is the only end-of-data signal that survives a capped `total`.

### Counting records by group

`GET /api/records/types/{key}/records/aggregate` answers "how many records per
X" without pulling the records. It is a `GROUP BY` over the same index tables
the list reads, through the same filter grammar, so the numbers it returns are
the numbers the list would show.

| parameter | does |
|---|---|
| `?group_by=` | an indexed field, a virtual field an index provider projects, or a fixed column (`status`, `locale`, `slug`, `position`, `published_at`, `created_at`, `updated_at`, `display_title`) |
| `?metric=` | `count` (the default), `sum:<number field>`, or `min:<field>` / `max:<field>` over a number, date, datetime or text field |
| `?filter=` | repeats, and means exactly what it means on the list |
| `?locale=` | shorthand for `filter=locale:eq:<tag>` |
| `?reduce=` | read a maintained aggregate instead — see **Maintained aggregates** below |

```
GET /api/records/types/order/records/aggregate?group_by=state&metric=sum:total&filter=status:eq:published

{"group_by": "state", "metric": "sum:total", "stored": false, "updated_at": null,
 "total_groups": 2, "truncated": false,
 "groups": [{"value": "CA", "count": 2, "sum": "15.00000", "min": null, "max": null},
            {"value": "NY", "count": 1, "sum": "7.00000", "min": null, "max": null}]}
```

Worth knowing:

- Every value comes back as a **string**, `count` excepted. A group read from
  a maintained aggregate is text by construction, and the two readings have to
  be comparable without per-field coercion.
- Groups are ordered by count descending, then by value, and capped at
  `max_aggregate_groups` (1,000 by default) with `truncated: true` when the
  cap was hit. What is dropped is always the long tail.
- **A multi-valued `group_by` counts a record once per value it holds**, so
  the counts sum to more than the number of records. That is the same reading
  `filter=tags:eq:red` has, and the only honest one for "records per tag".
- The trash is never counted, and a record with no value for the field is in
  no group at all (it has no index row). A *fixed column* that is `NULL` does
  produce a group whose `value` is `null` — the column exists.
- Refusals are the filter grammar's: an unknown field is a `400`, a declared
  but unindexed one is a `400`, and one that is mid-rebuild is a `409` — the
  same three you get for filtering on it.
- **It is not on the anonymous read API, and will not be.** An anonymous
  aggregate is an oracle over rows the caller cannot read: `group_by=status`
  reports how many unpublished drafts a type holds, and a `min`/`max` asked
  repeatedly under different filters reconstructs individual values a row at a
  time. `records.view` plus the type's `allowed_roles` gate it exactly as they
  gate the record list.

### Showing records on a page

When `simple_module_pagebuilder` is also installed, this module contributes a
**Records list** block to its Puck editor palette (category **Data**),
registered through `puck-blocks.ts` the same way `news`'s `NewsFeed` block is
— records knows about pagebuilder, pagebuilder does not know about records.

Drop the block on a page and pick:

| prop | meaning |
|---|---|
| **Record type** | any type this account can see; one that isn't public is still selectable, and shows "(not public)" in the list |
| **Fields to show** | which of the type's declared fields render beyond the title, and in what order — nothing beyond the title by default |
| **Filter** | one `field:op:value` term, e.g. `status:eq:paid` — indexed fields only, same grammar as the admin list |
| **Sort** | one field, e.g. `-published_at` for newest first |
| **How many** | 1–50 |
| **Layout** | list, cards, or table |
| **Heading**, **Text shown when there are no records** | freely edited copy |
| **Link template** | `{slug}` / `{uuid}` placeholders; blank means the title isn't a link |
| **Public API prefix** | advanced — only touch it if `public_route_prefix` (above) has been changed from its default |

**Only a public type's records ever reach a visitor.** The block fetches from
the anonymous read API (`GET {public_route_prefix}/{type_key}`), so a type
that is not (yet) marked `is_public` renders the empty state on the live site
— the editor additionally shows *why*, with a "only public types render on
the site" hint that a visitor never sees. The `typeKey` picker still lists
every type on purpose: it is what lets an author build the block ahead of
flipping the type public, and see the hint rather than a confusing blank
result.

**The public API never expands a relation** (see [Relations](#relations)), so
a `relation` field shown in the widget renders as its stored `type:uuid`, not
a linked title — the block's own field help says so. Everything else formats
the way the admin list does: booleans as `✓`/`–`, dates and datetimes in the
visitor's own locale, `select`/`multiselect` through their configured labels.

The block renders identically in the editor's live preview and on the
published page — both call the same anonymous endpoint with the same query,
so what an author sees while building the page is what a visitor gets.

## Settings

DB-backed via the framework's settings module — no `SM_RECORDS_*` environment
variables are read. Configure on the Settings screen or with
`scripts/set_setting.py`.

| setting | default | restart? |
|---|---|---|
| `public_route_prefix` | `/api/records/public` | yes |
| `content_locales` | `["en"]` | yes |
| `default_content_locale` | `en` | yes |
| `default_page_size` | 25 | no |
| `max_page_size` | 200 | no |
| `revision_limit` | 50 per record | no |
| `max_payload_bytes` | 262144 (256 KB) | no |
| `max_count` | 10000 | no |
| `max_filter_terms` | 20 | no |
| `max_sort_terms` | 5 | no |
| `max_in_values` | 200 | no |
| `preview_sync_limit` | 5000 | no |
| `preview_job_ttl_seconds` | 600 (10 min) | no |
| `max_import_bytes` | 52428800 (50 MB) | no |
| `max_import_rows` | 20000 | no |
| `public_cache_seconds` | 60 | no |
| `max_fields_per_type` | 100 | no |
| `max_indexed_fields_per_type` | 25 | no |
| `reindex_batch_size` | 500 | no |
| `reindex_stale_after_seconds` | 900 (15 min) | no |
| `menu_refresh_seconds` | 5 | no |

`content_locales` and `default_content_locale` are the languages records may
be authored in — see [Content languages](#content-languages).

`menu_refresh_seconds` is the sidebar's refresh window — see
[Sidebar entries](#sidebar-entries).

`max_count` is how far a list page's `total` is counted exactly — see
[Paging a large type](#paging-a-large-type). `preview_sync_limit` is the
largest type a schema preview will dry-run inside the request, and
`preview_job_ttl_seconds` is how long a finished preview's report stays
reusable by the save that follows it — see
[Changing a schema that already holds records](#changing-a-schema-that-already-holds-records).

`public_route_prefix` is one of the three settings above a change to needs a
restart, and the only one whose reason is about routes. The routes it
configures are mounted — and exempted from authentication — while
the app boots, because the prefix only exists as the operator set it once the
host has hydrated these settings from the database.

It is validated on save: it must start with `/`, must name at least one path
segment, and may not be `/api`, `/admin`, `/api/records`, `/admin/records` or
a parent of any of them. The exemption it registers disables `AuthMiddleware`
for every `GET`/`HEAD` under it — host-wide, not just for this module — so a
parent path would hand the admin surface to anonymous callers and an empty
value would hand them the whole site. A value *under* the admin API's prefix
is harmless; the exemption cannot reach upwards. A stored value that predates
this rule is logged as an error at boot and replaced by the default rather
than failing the lifespan: the only screen that could fix it lives in the app
that would not start.

## Relations

A `relation` field stores `{"type": "<type_key>", "uuid": "<record uuid>"}` —
and a row in the reference index, which is what makes both directions cheap.

**Forward: `?expand=`.** `GET /api/records/types/{key}/records` and
`…/records/{uuid}` take `?expand=field_a,field_b` and resolve those relation
fields to **depth one**, one batched query per named field for the whole page.
Each reference comes back under `expanded[field_key]`, in payload order, in
exactly one of three states:

- **resolved** — `display_title`, `slug` and `status` are filled;
- **dangling** — the target is in the trash, gone, or not a record of the
  type the field declares; `display_title` is `null`. A restorable delete must
  not break what references it, so this is a flag rather than an error or a
  dropped entry. A to-many entry that is not a reference at all (a `null` left
  by a payload written before that was refused) keeps its slot as one of
  these, because `expanded[key]` is rendered positionally against `data[key]`;
- **restricted** — the target's type narrows `allowed_roles` past the caller.
  Nothing but the uuid the caller already holds in `data` comes back.

A key that is not a relation field of the type is a `400` naming it. Depth
greater than one is not supported; the admin list and record editor always
expand every relation column they render, so "opt-in" describes the API rather
than the UI.

**Reverse: referrers.**
`GET /api/records/types/{key}/records/{uuid}/referrers?page=&page_size=`
answers "what points at this record", from the reference index rather than a
scan, and each entry carries the referring field's label and its `on_delete`
so a delete dialog can say *why* a delete would be blocked. Trashed referrers
are listed and flagged `is_deleted` (the delete path itself still ignores
them), and a trashed *target* answers too for a caller holding `records.edit`
— that is the screen where "what still points at this?" decides between
restore and purge.

Three numbers come back, and each means something different:

- `total` counts every referring **record**, live, trashed, visible or not.
  One record pointing at the target from two relation fields is one referrer
  here and two `items` (the panel names the field). It is the number a
  `restrict` refusal and the delete dialog speak, and the editor's
  "Referenced by" badge is the same number from the same helper.
- `hidden` is how many of those the caller may not view, because their type
  narrows `allowed_roles` past them. Stated rather than left to subtraction —
  a panel showing two of four with no explanation reads as a bug.
- `items` is the visible rows, **paginated over the visible set alone**, so
  walking pages cannot locate the hidden ones. All three are counted and
  windowed in SQL, so a page costs the page rather than the graph.

A `restrict` refusal (`409` on a delete) speaks the same three numbers:
`detail` counts every blocker, `referrers` lists at most 50 uuids of the ones
this caller may read, `more` says how many visible blockers are not listed,
and `hidden` counts the blockers whose type narrows `allowed_roles` past them
— counted, never named, exactly as the panel does.

## Public read API

Off by default and per type. Setting `is_public` on a Record Type serves its
published records anonymously at two routes, under `public_route_prefix`
(default `/api/records/public`):

| route | answers |
|---|---|
| `GET`/`HEAD` `{prefix}/{type_key}` | `{items, total, total_capped, page, page_size, next_cursor}` |
| `GET`/`HEAD` `{prefix}/{type_key}/{uuid}` | one record |

A record reads back as `uuid`, `slug`, `locale`, `translations`,
`display_title`, `published_at` and `data` — nothing else. The audit columns, `version`, `status`, `invalid` and
the reserved `_orphaned` sub-key (a deleted field's retained values, which are
the admin's undo buffer) are removed from the *shape*, not filtered out of the
query.

The rules worth knowing before you point a site at it:

- **A type that is not public is a `404`, identical to one that does not
  exist**, by key and by uuid alike. A draft, a trashed record and an unknown
  uuid answer with that same body, so nothing here can be used to enumerate
  what an install holds.
- **The filter and sort grammar is the admin one, over indexed fields and the
  public shape's own columns only.** Indexed declared fields, plus `slug`,
  `display_title` and `published_at`. `status`, `position`, `created_at` and
  `updated_at` are removed from the shape and therefore from the grammar —
  otherwise an anonymous caller could binary-search an audit timestamp it
  cannot read. A filter or sort naming one of those, or a field that is
  unindexed, non-existent or mid-reindex, is the same `400` naming the field —
  never the admin API's `409`: "cannot" and "cannot right now" are the same
  answer to a caller who has no business seeing operational state.
- **`?locale=` names the language the listing is of, and its absence means
  `default_content_locale` — never "all".** An anonymous reader is asking for
  one site, and merging languages into one list is how a German record ends up
  rendered on an English page. A locale that is not configured is a `400`
  naming it and listing the ones that are; that is the site's own front door,
  not an oracle over private content. The by-uuid route is **locale-blind** and
  ignores `?locale=`: a uuid names exactly one record, in exactly one language.
  `translations` lists that record's **published, live** siblings — `locale`,
  `uuid` and `slug` each — so a site can render a language switcher without
  advertising an address that answers `404`. It is resolved in one batched
  query per page, never one per row.
- **No `?expand=`** — an anonymous caller must not be able to turn one request
  into a batch of joins against other types, some of which may not be public.
  `expand` and `trashed` are simply not parameters here; unknown ones are
  ignored.
- `page_size` is clamped to `max_page_size` rather than refused.
- **`?after=`, `?total=false` and the `max_count` bound apply here too** — see
  [Paging a large type](#paging-a-large-type). A client walking a large public
  type is precisely the caller that should not be paying for an `OFFSET` and a
  count it never reads.
- **Both reads are cacheable.** They carry a weak `ETag` over the content they
  are about to return and `Cache-Control: public, max-age=N`, where `N` is the
  `public_cache_seconds` setting (60 by default). A conditional GET whose
  `If-None-Match` matches is a `304` with no body. Set it to `0` for
  `Cache-Control: no-store` and no validator, on an install whose "published"
  means "visible the instant it is saved".

  > A *shared* cache still cannot store these on a stock host: every anonymous
  > response also carries `Vary: Cookie` and a fresh `Set-Cookie: session=…`,
  > written on every request by the framework's `InertiaLayoutDataMiddleware`
  > (`simple_module_hosting/_inertia_shared.py:54`). This module writes nothing
  > to the session and does not work around it; until that is fixed upstream,
  > the headers help a browser and a private cache rather than a CDN.

## Permissions

Three static permissions, registered at boot and visible in the role editor:
`records.view`, `records.edit`, `records.manage_types`.

Record Types are created at runtime, after the database is open, but
`register_permissions` runs at app construction, before it — so **per-type
permissions cannot be framework permissions**. Each `RecordType` instead
carries its own `allowed_roles`, narrowing which roles may write records of
that type on top of the static `records.edit`/`records.manage_types`
permission; an empty list means "any role holding the static permission".

`allowed_roles` narrows, and narrowing has no exceptions: a caller holding
the `admin` wildcard is refused on a type whose `allowed_roles` is non-empty
unless `admin` is one of the roles listed. So an admin creating a restricted
type must list a role they actually hold, or else use `records.manage_types`
to edit `allowed_roles` back before they can work with its records. The same
list also governs what a delete elsewhere may do to this type's records: a
`cascade` or `set_null` relation pointing here is refused — reported as a
`restrict` blocker — for a caller the list excludes, and
`DELETE /api/records/types/{key}` (which purges every record of the type,
trash included) and an `orphaned: "discard"` schema edit are refused for them
too, `records.manage_types` notwithstanding.

**It narrows reads exactly as it narrows writes — same rule, same `403`.** A
caller the list excludes is refused every *record* surface of that type:

- `GET /api/records/types/{key}/records`, `…/records/{uuid}`, its
  `…/referrers` and its `…/revisions`;
- the admin screens over them — `/admin/records/{key}`, `/{key}/new` and
  `/{key}/{uuid}`;
- `GET /api/records/types` and the Record Types screen *omit* the type
  altogether, rather than listing a card that 403s when opened.

One thing stays visible, and it is about the schema rather than the records:
a **`records.manage_types` holder** reads `GET /api/records/types/{key}` —
with `…/revisions` and `…/export`, which are the same definition by other
routes — and opens the type editor at `/admin/records/types/{key}`, whatever
`allowed_roles` says. A manager locked out of the screen that edits
`allowed_roles` would be a one-way door. That is the whole exception: a
caller holding only `records.view` gets the same `403` on those three routes
as on every record surface of the type, because the definition names every
field and the `allowed_roles` themselves, and `TypeRead` carries a live
`record_count` of records they may not list.

A relation pointing *at* a narrowed type is a different question and is not a
refusal: an `?expand=` of it comes back `restricted` (see Relations), because
the caller is reading a record they are entitled to see that happens to point
somewhere they are not.

**This is an honest limitation, not an oversight: per-type `allowed_roles`
are invisible in the framework's role editor.** An admin editing roles sees
only the three coarse permissions above and has no way to discover, from that
screen, that a given type is further restricted to specific roles.

## Data model notes worth knowing before you rely on them

- **`number` fields are stored with five decimal places, and that contract is
  approximate on SQLite.** The index column is `Numeric(19, 5)`; a value the
  index would round is refused on write rather than silently stored with the
  payload and index disagreeing. SQLite has no native decimal type, so
  SQLAlchemy stores `Numeric` there as a floating-point `REAL` — exact on
  Postgres, approximate on SQLite. Callers wanting more precision want a
  `text` or `json` field instead.
- **Some field keys are reserved.** A field may not be keyed `_orphaned`, nor
  after any column a record already has — `id`, `uuid`, `type_id`, `data`,
  `schema_version`, `version`, `status`, `slug`, `locale`,
  `translation_group`, `display_title`, `position`,
  `published_at`, `created_at`, `updated_at`, `created_by`, `updated_by`,
  `is_deleted`, `deleted_at`, `deleted_by`. The query layer resolves those
  names against the record row before the type's own fields, so such a field
  would index correctly and then be filtered and sorted from the wrong data.
  The list is derived from the model, so it cannot drift.
- **A `relation` field is always indexed**, whatever the checkbox says: the
  flag is normalised on, exactly as `unique` is. `on_delete` is enforced by
  asking the reference index who points at a record, so an unindexed relation
  would accept `restrict`/`set_null`/`cascade` and enforce none of them.
  Indexed relations count against `max_indexed_fields_per_type`.
- **`allowed_roles` narrows reads and writes the same way: a `403`.** What is
  *redacted* rather than refused is a reference **to** a narrowed type from a
  record the caller may read — an `?expand=` of it comes back `restricted`,
  and a referrer of one is counted in `total`, reported in `hidden` and left
  out of `items`. That is not a weaker rule applied to the same resource: the
  caller is reading a record they are entitled to see that happens to point
  somewhere they are not, and asking that type directly is still a `403`.
- **`display_field` must point at a `text`, `select`, `email`, `url`,
  `integer`, `number`, `date` or `datetime` field, and `slug_field` at a
  `text`, `select`, `email` or `url` one.** The rest do not stringify into
  anything a title or an address should be.
- **`required` on a `text`, `longtext`, `email`, `url` or `select` field is
  not satisfied by `""` or whitespace.**
- **The trash is enumerable**: `GET /api/records/types/{key}/records?trashed=true`
  returns only that type's soft-deleted records, with `total` counted the same
  way and the usual filters and sorts. It needs `records.edit`, not merely
  `records.view` — enumerating the trash is how anything gets restored.
- **`unique` is enforced by the application, not by a database constraint.**
  The index tables are shared across every field of a kind, so a partial
  unique index naming a runtime-chosen field key isn't possible. A `unique`
  field is checked with a `SELECT ... LIMIT 1` inside the write's transaction —
  among the records that are not translations of the one being written, see
  [Content languages](#what-this-buys-and-what-it-costs) — and writes to the
  type are serialized to close the check-then-act race between two concurrent
  creates: a row lock on the type on Postgres, and a write against the type row
  — which takes SQLite's `RESERVED` lock — on SQLite, where `FOR UPDATE` locks
  nothing. This is "unique enforced at the cost of serializing writes on that
  type," not a database-level uniqueness guarantee. **Both halves are
  measured**: twenty concurrent creates of one value on Postgres and eight on
  SQLite each store exactly one row and refuse the rest with a `409` — see
  [`docs/postgres-2026-09-21.md`](docs/postgres-2026-09-21.md) § 4.
- **A write costs fewer SQL statements on Postgres than on SQLite, and the
  difference grows with the number of indexed fields.** `write_index` batches
  its index rows into one `INSERT` per *kind table* on Postgres and one per
  *row* on SQLite, so a create is 10 statements against 13 on the demo
  `company` type and 7 against 14 on a type with eight indexed `text` fields.
  Nothing else in the module differs: every other statement count, and every
  plan shape, is the same on both. Any "N statements per write" figure quoted
  elsewhere is SQLite's.

## Collections

Off by default, and off for every host that does not write a line of Python to
turn it on. A **collection** gives one Record Type (or several) its own
document, revision and index tables instead of sharing the global ones — the
escape hatch for a type that dwarfs the others.

### Declaring one

The tables have to exist in the host's Alembic history, so a collection cannot
be a setting read from the database at boot. It is declared in code, in a
module the host imports **before** `create_app`:

```python
# host/records_collections.py
from sm_records.collections import declare_collection

declare_collection("events")
```

```python
# host/main.py
import records_collections  # noqa: F401 - declares this host's collections

app = create_app(settings)
```

That call builds a full table set on the module's metadata with the prefix
`records_c_events_`: `record`, `revision` and the six index tables. Each one is
built by the same factory that builds the global set, so it is identical in
shape modulo the prefix — same columns, same indexes, same partial unique slug
index, same foreign keys pointing at the collection's own record table. The
host then autogenerates **one migration** for the new tables, exactly as it did
for the module itself:

```
alembic -c host/alembic.ini revision --autogenerate -m "records events collection tables"
alembic -c host/alembic.ini upgrade heads
```

The host's `alembic/env.py` has to import that declaration module, or
autogenerate cannot see the tables. In this repo `host/alembic.ini` sets
`prepend_sys_path = %(here)s` and `env.py` imports `records_collections` when
it exists.

A name must match `^[a-z][a-z0-9_]*$`, be at most 22 characters (it is a
table-name prefix, and the longest index built on it —
`ix_records_c_<name>_record_type_status_position` — has to fit inside
Postgres's 63-byte identifier limit, which at 22 it exactly does), and not be one of `default`, `global`,
`records`, `type`, `index`, `reduce`. Declaring the same name twice is a no-op;
declaring one **after** the app has been built is a `RuntimeError`, because
those tables are in no migration and every write to them would be a
`no such table` found at runtime instead.

### Assigning a type to one

`POST /api/records/types` takes `collection`, and that is the only request that
may set it:

```json
{"key": "event", "label": "Event", "collection": "events", "fields": [...]}
```

An undeclared name is a `422` naming what *is* declared. Omitting it — or
sending `null` — puts the type in the shared tables, which is what every type
created before this existed carries.

**A type cannot be moved between collections.** `PUT /api/records/types/{key}`
answers a changed `collection` with a `409` and the sentence *"moving a
populated type between collections is not supported"*. It would mean copying
the type's records, revisions and index rows into other tables and re-pointing
every reference at them, with no rollback story; the honest answer is to export
the type, delete it and re-import under a new one. An echo of the current value
is accepted, so a client that sends back the whole type it just read still
saves. The type editor shows the collection read-only once the type exists and
offers the declared set only on the "new type" form.

### What stays global

`records_type`, `records_type_revision`, the reduce table, the settings, the
permissions, the health check and the CLI. The reduce table in particular:
a reduce row is a *fold* keyed by `type_id` with no `record_id` to partition
on, so a collection would gain nothing from its own copy and gain one more
table to rebuild. The CLI takes a type and follows its collection.

### Relations across a collection

They work in both directions, and nothing about declaring a relation mentions
a collection. A `relation` names its target by `(type, uuid)`, the **target
type** decides which tables are read, and `on_delete` — `restrict`, `set_null`
and `cascade` alike — crosses the boundary like any other edge.

Two consequences are worth knowing:

- **"Who references this record" asks every table set.** A reference row lives
  in the *referrer's* collection tables and names `target_uuid` +
  `target_type_id`, so the rows pointing at one record are scattered across
  every set that holds a type relating to it. The referrers query is a loop —
  one indexed lookup per declared collection plus one for the global set —
  rather than a `UNION`, because the ids a reference table returns are ids in
  *its own* record table and a union would merge them and lose which is which.
  That is a query per declared collection on the delete path and on the
  referrers panel; it is the cost of the partition, and it is why collections
  are a per-type escape hatch rather than a default.
- **`?expand=` is still one batched query per field.** The target type decides
  the table, so expanding a field that points into a collection reads that
  collection's record table once for the whole page.

### `uuid` across collections

**A record's `uuid` is unique across every table set**, and both halves of that
are enforced rather than assumed.

The database enforces uniqueness only *within* a table — each record table
carries its own unique index, and no constraint spans them — so the rule is
held by the write path: `uuid4` for everything the writer and the seeder
create, and an explicit check for the one writer that keeps an identifier from
outside. **The importer preserves a file's `uuid` verbatim** (that is what
makes a round trip idempotent), so importing a global type's export into a
collection type used to plant a duplicate deterministically. It now refuses the
row:

```
uuid 9d0c… already exists in collection 'events'; a record's uuid is unique
across every table set, so a file cannot create a record under one that is
already in use
```

It is a row error, so `on_error=abort` refuses the whole file before writing
anything and `on_error=skip` reports the row and imports the rest, and the
**dry run predicts it** like every other row error. A host that declares no
collection pays nothing for the check: there is no other table set to ask.

**Moving a type's records into a collection is therefore purge-then-import,
in that order.** Export the global type, delete it (which purges its records),
create the type again with `collection=`, then import. Importing first and
deleting afterwards is the sequence the refusal is about.

Independently of the data, everything that resolves a record by uuid keys on
**`(target_type_id, target_uuid)`** and takes its table set from the declared
type — the referrer query, `referrer_count`, the delete plan's `restrict`,
`set_null` and `cascade` walks, the relation write check and `?expand=`. So a
duplicate that somehow exists (a hand-written row, a restore from a backup
taken before this rule) cannot make a delete cascade into an unrelated record
or a relation write be refused against a record that is exactly what it claims
to be.

### Inert when unused

With no `declare_collection` call, the module's metadata holds exactly the
tables it held before collections existed, `alembic check` reports no
operations beyond the one nullable `records_type.collection` column,
`tables_for` always returns the global set, and the query layer runs the same
statements it always did. There is one migration such a host applies (the
column) and one it can skip (whatever tables a *different* host's collections
needed).

## Content languages

Off by default, per host **and** per type. An install that leaves
`content_locales` at `["en"]` and never sets `translatable` on a type runs
exactly the code it ran before this existed: every record is in one language,
no screen offers another, and the public API behaves identically.

### Configure the host

```
python scripts/set_setting.py sm_records content_locales '["en","de"]'
python scripts/set_setting.py sm_records default_content_locale en
```

Both need a restart. Each tag must be a lowercase language tag (`en`, `de`,
`pt-br`), and the default must be one of them. Resolution from a query string
is case-insensitive — `?locale=DE` finds `de` — but the configured list is not,
so two spellings of one language can never address two different sets.

**These are this module's own settings, not `pagebuilder`'s.** `records` is
published on its own and a host may install either without the other, and the
two may legitimately publish in different language sets — an English-only
product catalogue beside a four-language marketing site is a real
configuration, not a mistake. A host that wants them aligned sets both:

```
python scripts/set_setting.py pagebuilder content_locales '["en","de"]'
python scripts/set_setting.py sm_records  content_locales '["en","de"]'
```

Both are distinct again from the host's `SM_I18N_SUPPORTED_LOCALES`, which
decides what language the *admin console* speaks rather than what the content
is published in.

### Turn it on for a type

`translatable` on a Record Type. Turning it **on** is additive — every
existing record already carries the default locale. Turning it **off** while
records in another locale exist is a `409` naming the count: those records
would otherwise stay in the database, keep their slug claims, keep answering
`?locale=`, and be unreachable from a UI that no longer offers their language.

### A record's language is fixed for its lifetime

There is no `locale` on `PUT /records/{uuid}` — a body carrying one is a `422`,
refused rather than quietly dropped. `POST /records` takes one (defaulting to
`default_content_locale`; a type that is not `translatable` accepts only that).
Everything after that is a **translation**: a whole sibling record, never a
per-field overlay.

| route | does |
|---|---|
| `POST /api/records/types/{key}/records/{uuid}/translations` | creates the sibling — `records.edit` plus the type's `allowed_roles` |
| `GET /api/records/types/{key}/records/{uuid}/translations` | lists the group, the record itself and trashed siblings included |
| `GET /api/records/types/{key}/records/{uuid}?translations=true` | the same list, on the record — never on the list endpoint, where it would be one query per row |

The new record joins the source's `translation_group`, copies its payload and
`position`, starts as a **draft** whatever the source's status, and gets a slug
regenerated *in the target locale* — suffixed `-2`, `-3`… if something there
already holds it. An explicit `slug` is used as given and refused with a `409`
if it is taken in that locale.

Refusals: a type that is not `translatable` (`409`), a locale that is not
configured (`422`, naming it), a source already in the target locale (`409`),
and a sibling that already holds that language (`409`) — **including a trashed
one**, which keeps its claim until it is purged or restored.

### What this buys, and what it costs

- **Slugs are unique per `(type, locale)`**, not per type. The same word is the
  address in both languages, because they are two documents at two addresses.
  Trash keeps its claim per locale, as it always did per type.
- **One record per `(translation_group, locale)`**, enforced by a unique index,
  so a double submit cannot produce two German siblings.
- **Deleting a record never touches its siblings.** A translation group is a
  grouping, not a cascade.
- **`locale` is a filterable, sortable fixed column** — `?filter=locale:eq:de`,
  `?sort=locale` — and is therefore a reserved field key. The admin list
  defaults to **all** locales, because an editor's question is "what exists",
  not "what exists in English".
- **`allowed_roles`, `is_public` and `on_delete` are type-level and
  locale-blind.**
- **`unique` is enforced among records that are not siblings.** A `unique`
  field is still unique across the whole type and across every language — two
  records in the same locale, or in two locales but in different translation
  groups, collide exactly as they did before. What is exempt is the group
  itself: records sharing a `translation_group` do not claim against each
  other, because a German product legitimately carries the English product's
  SKU. So a translation may copy a `unique` value (it copies the whole
  payload), editing the source afterwards leaves the sibling's now-stale copy
  alone, and a trashed sibling keeps its exemption while a trashed unrelated
  record still blocks.
- **There is no per-field translation**, no automatic translation, and no
  fallback on the public API: a missing `de` sibling is a `404` for
  `?locale=de`, not the `en` record in disguise.
- **There are no locale-scoped redirects.** Records have no public *pages* —
  only a JSON API keyed by uuid and slug — so a rename strands no URL the way
  a page rename does.

### Dropping a content language

**Removing a tag from `content_locales` is not refused at save**, deliberately
— the alternative makes a typo unfixable, and the records written in that
language are still perfectly good records. Here is exactly what happens to
them:

- the public listing stops naming the language (`?locale=de` is a `400`
  listing the languages the site does publish);
- the public **by-uuid** read is a `404`, and the language switcher on a
  sibling stops advertising it. A language the site says it does not publish
  cannot go on being served;
- the **admin** API is untouched: the records list, read, edit, export and
  delete exactly as before. An operator has to be able to reach them, which is
  the whole reason the save is not refused;
- `/health/ready` degrades with an `orphaned_locales: {de: 12}` detail naming
  each stranded language and how many records are in it.

The count is taken **once, at startup** (the framework's settings registry
offers no post-hydration hook to recompute it from), so it appears after the
restart the setting needs anyway. To find them at any time:

```
GET /api/records/types/{key}/records?filter=locale:eq:de
```

Then translate them into a language you do publish, or delete them. Adding the
tag back restores everything — nothing was rewritten.

### Export and import

The export gains `locale` and `translation_group` columns and the import reads
them back: a missing `locale` defaults to `default_content_locale` (a file
written before the install spoke more than one language is a file of
default-locale records), and a locale that is not configured is that row's
error. A row that asks to change an existing record's locale or move it
between groups is refused, exactly as `PUT` is.

**`translation_group` is carried verbatim but not taken on trust.** A group is
a uniqueness exemption (see above), so a row that *creates* a record may name
only a group it is entitled to: its own `uuid`, a group another row of the
same file also carries (a translated pair travelling together — an export of a
group always contains the whole group), or a group this type does not have
yet. Naming a group this type already holds and the file does not describe is
a row error:

```
translation_group ab03… names a group not in this file; create translations
through POST /api/records/types/art/records/{uuid}/translations
```

Another *type*'s group is not a collision and not a forgery: groups are scoped
by type everywhere that reads one, index included.

## Changing a schema that already holds records

Every change to a type's fields is diffed against the current schema and
classified before anything is written — **additive**, **index-affecting**,
**restrictive** or **destructive** — and `POST /api/records/types/{key}/schema/preview`
returns that classification together with a dry run over every existing
record (trash included) so you can see what would break before saving.

- A **restrictive** change (a new required field, a narrowed type, a
  tightened constraint, a removed choice, a newly unique field) is refused
  with the report unless every record passes. Send `force: true` to apply it
  anyway: the failing records are **marked, not rewritten** — they read back
  with `invalid` naming the fields, and the editor shows it.
- A **destructive** change (removing a field) keeps the value on each
  record; it moves under the reserved `_orphaned` key on that record's next
  write. Re-adding a key that still holds orphaned values is refused until
  you choose `orphaned: "restore"` (the old values read back and index) or
  `"discard"` (they are dropped — the one bulk write the module ever does,
  and it touches only that sub-key).
- An **index-affecting** change (toggling `indexed`, changing an indexed
  field's type, re-pointing a `relation` at another type or flipping its
  `many`, or changing `display_field`) applies immediately and
  enqueues a rebuild: the field appears in the type's `reindex_pending` and
  refuses filters and sorts until the rebuild has moved its rows and cleared
  the entry. The rebuild runs as a background task after the request.
- `slug_field` changes never regenerate existing slugs — a slug is an
  address, and regenerating could break links or collide with a slug handed
  out since. Only records written after the change use the new pointer.

**A preview is `records.manage_types`, not `records.view` on the type.**
`POST .../schema/preview` deliberately opens to anyone who can open the schema
screen (§10), and its report lists up to ten failing records by `uuid` and
`display_title`. So a caller holding `manage_types` but outside a type's
`allowed_roles` sees those titles. That is pre-existing and intentional —
somebody editing a type's schema has to be able to see what their change would
break — but it is worth knowing before you use `allowed_roles` to hide titles
from an administrator: it hides them from the record API, not from a schema
preview of the type.

**A preview of a big type runs as a job.** The dry run validates every record
of the type, trash included, at roughly a thousand records a second — a few
seconds on a small type and minutes on a large one, with whatever proxy
timeout that implies. `POST .../schema/preview` therefore answers `200` with
the report up to `preview_sync_limit` records (5,000 by default) and
`202 {"job": "...", "status": "running"}` above it, running the scan after the
response. Poll `GET /api/records/types/{key}/schema/preview/{job}` for
`{status, checked, total, preview}`; the type editor does this once a second
and shows "Checked N of M…". A `404` from the poll means this process no
longer holds the job — the registry is in-memory and bounded, by design, since
§8.9 refuses to persist a report about records that may have changed — and the
answer to one is simply to preview again, which writes nothing.

Saving straight after a preview does not scan twice. `PUT /types/{key}` reuses
a completed job's report when it was taken against the same type, the same
proposed fields **and the same `version`** — the value the caller already has
to send as `expected_version` and which the save has already checked under the
type's row lock, so the schema the report describes is provably the schema
being changed. What that does not cover is records written in between, which
is what `preview_job_ttl_seconds` bounds (10 minutes by default); set it to
`0` to make every save run its own pass. A save with no matching preview, or
one resolving orphaned keys with `discard`, always runs its own.

Field keys are immutable: a "rename" is a remove plus an add, and is
treated as one. Every schema change writes a type revision;
`POST /api/records/types/{key}/revisions/{version}/restore` rolls back
through the same pipeline, so a rollback that would fail records is refused
like any other change.

## Import and export

Records and type definitions both move as files. Everything below goes through
the same service code the UI and the API use — an import writes with
`create_record`/`update_record`, so revisions, index rows, `unique` and slug
claims and the per-type lock all behave exactly as they do for a single save.

| route | permission | notes |
|---|---|---|
| `GET /api/records/types/{key}/records/export?format=json\|csv` | `records.view` | streaming; takes the list screen's `filter`/`sort` (a refused one is the list's `400`, before any download starts), and `trashed=true` (which costs `records.edit`) |
| `POST /api/records/types/{key}/records/import` | `records.edit` | multipart `file=`, or a raw body with `Content-Type: application/json` / `text/csv` |
| `GET /api/records/types/{key}/export` | `records.view` | the type definition alone, shaped for the route below; narrowed by the type's `allowed_roles` unless the caller holds `records.manage_types`, exactly as `GET /types/{key}` is |
| `POST /api/records/types/import` | `records.manage_types` | `mode=create` (default) or `mode=update` + `expected_version` |

The record export **streams**. It walks the type keyset-paged by `id` in
batches of `reindex_batch_size`, on a session of its own, so a 100k-record
type is exported in constant memory rather than assembled in one list. (An
export with an explicit `?sort=` cannot be keyset-paged — the sort key lives
in an index table — and pages by `OFFSET` instead; it is meant for exporting a
*selection*, and the unsorted default is what a round trip should use.)

**What travels.** Each record carries `uuid`, `slug`, `locale`,
`translation_group`, `status`, `position`, `published_at` and `data`; `data`
is the lenient read, so defaults are filled in and a record stamped at an
older schema version exports under the current one. Relations travel as stored (`{"type": …, "uuid": …}`), never expanded.
The reserved `_orphaned` key, the audit columns, `version` and `is_deleted` do
not travel: they describe this install's copy of the row. `uuid` does, which
is what makes a round trip independent of autoincrement.

**CSV.** Columns are `uuid, slug, locale, translation_group, status,
position, published_at` and then one per declared field in declaration order;
import is header-driven, so order and missing columns are fine (a missing column means "leave it alone", an empty
cell means null). Values use the module's own wire forms — a `number` is its
decimal string, a boolean is `true`/`false`, a date is ISO. `multiselect`,
`json` and `media` cells are JSON-encoded; a relation is `type:uuid`, and a
to-many relation a JSON list of those. UTF-8 with **no** BOM, `\r\n` line
endings per RFC 4180.

> **CSV formula injection is escaped, losslessly.** A cell beginning `=`, `+`,
> `-`, `@`, a tab, a carriage return **or an apostrophe** is written with a
> leading apostrophe, which Excel and LibreOffice both read as "the rest of
> this cell is literal text" — so a `text` value of `=cmd|' /C calc'!A0`,
> chosen by anyone who can create a record, no longer runs in the spreadsheet
> of whichever admin clicked Export. Escaping the apostrophe *itself* is what
> keeps the round trip exact: the importer strips exactly one leading
> apostrophe from every cell, so a value that genuinely starts with one
> survives. The one cost is a CSV written **by hand** rather than exported —
> it carries no doubling, so a hand-typed `'12` imports as `12`.

**Import options** (query string, or multipart form fields, which win):

- `dry_run` — **`true` by default.** A dry run parses, validates and matches
  every row and returns the full report, writing nothing.
- `mode` — `upsert` (default; match, else create), `create`, `update`.
- `on_error` — `abort` (default) is all-or-nothing: the request's transaction
  is rolled back and the 422 carries the report. `skip` writes the valid rows,
  each under its own savepoint, and reports the rest.
- `match_by` — `uuid` (default), `slug`, or the key of a **`unique`** field.
  Matching on a non-unique field is refused rather than resolved arbitrarily.
  `slug` matches on the *canonical* slug — the cell is slugified first, the
  same way a write would store it, so a hand-written `Hello World` matches
  the record whose slug is `hello-world`. Matching on anything but `uuid`
  also refuses a row whose `uuid` already exists but whose match key found
  nothing: the record's slug or unique value has moved since the file was
  written, and creating it would collide on `uuid`.
- `force` — an update whose row carries no `version` is refused, because the
  export deliberately does not carry one; `force=true` accepts last-write-wins.
  The refusal is decided in the planning pass, so **a dry run predicts it**:
  the preview reports the row as failed rather than promising an update the
  apply would then refuse.
- `max_import_bytes` (a setting, 50 MB by default) refuses a larger body with
  `413` **before** parsing it — `Content-Length` first, and then while the
  body is read, so a chunked upload that declares no length is stopped at the
  first byte over the ceiling rather than buffered whole and refused
  afterwards.
- `max_import_rows` (a setting, 20,000 by default) refuses a file with more
  rows than that, also `413` and also before anything is written. The byte
  ceiling bounds the *file*; this bounds the *work*, because 50 MB is roughly
  1.7 M rows and that is hours inside one HTTP request — long past any reverse
  proxy's read timeout, at which point the client sees a 504 while the server
  keeps writing. A JSON file is counted exactly from the parsed document; a CSV
  is counted as it is read and the parse stops at the first row past the
  ceiling, because a quoted cell may contain newlines and there is no cheap
  exact count to check first.

The report is `{dry_run, mode, total, created, updated, skipped, failed,
errors: [{row, uuid, field, message}], errors_truncated, duration_ms}`, with
`created + updated + skipped + failed == total` and at most 200 errors listed.
**`skipped` is why re-importing an export is a no-op**: a row the record
already agrees with is not written at all, so versions do not move.

A row is refused for carrying `_orphaned`, naming an unknown field, pointing
at a relation target that does not exist, repeating a `uuid` already used
earlier in the same file, naming a `uuid` that belongs to another type or to
[another table set](#uuid-across-collections), matching a record in the trash
(restore or purge it first), naming a
[translation group it may not join](#export-and-import), or updating a record
without a `version`. **Every one of them is decided before anything is
written**, so a dry run and the apply that follows it report the same rows: a
check the write path could see and the planning pass could not is the one bug
this arrangement exists to prevent.

The handful of refusals that genuinely cannot be predicted — a slug two rows of
the same file both derive, which neither row can claim until the other is
written — are reported with **the row that failed**, not as row `0`.

**Type definitions.** `POST /api/records/types/import` with `mode=update` and
an `expected_version` routes through the ordinary `update_type` path, so
importing a definition onto a populated type is classified, dry-run and
refused with the same report — and answered with the same `force` /
`orphaned` — as the same change made in the schema editor.

**It writes what the file contains and nothing else.** Like `PUT
/types/{key}`, the update is built with `exclude_unset`: a definition that
does not mention `allowed_roles`, `is_public` or `translatable` leaves all
three as they are, rather than clearing them to the defaults. A file that
*does* name `allowed_roles`, and names a different list from the stored one,
costs the caller the type's own narrowing on top of `records.manage_types` —
widening a list you are outside of is a thing to ask for in the schema
editor, not a side effect of importing a file. An export re-imported onto the
install it came from sends the list already stored, so a round trip is
unaffected.

**`collection` travels with the definition.** It is a property of the
definition rather than of this install's copy of it — unlike `record_count` or
`version`, which is why those do not travel and this does. On a create, a name
this host has not declared is the same `422` `POST /types` gives; on
`mode=update`, a value that differs from the stored one is the same `409` `PUT
/types/{key}` gives, because a collection is assigned at creation and never
after. Dropped from the export, as it was, a collection-backed type landed on
the next install as a shared-tables type with no warning anywhere.

**From the command line** (from the repo root, like every entry point here):

```bash
python -m sm_records.cli export --type order --format json --out order.json
python -m sm_records.cli export --type order --format csv          # stdout
python -m sm_records.cli import --type order order.json            # dry run
python -m sm_records.cli import --type order order.json --apply
```

`import` is a dry run unless `--apply`, takes `--mode`, `--on-error`,
`--match-by` and `--force`, and exits non-zero with the report printed when an
`abort` run is refused.

## Development

```bash
uv sync --extra dev
uv run pytest
```

### Running the suites against Postgres

Both suites default to SQLite — in-memory for the unit tests, a reused file
for the perf measurements — and both take an opt-in URL instead. CI is
unchanged by either; nothing is selected unless the variable is set.

```bash
# unit suite: a real database, emptied (TRUNCATE ... RESTART IDENTITY) per test
cd modules/records
SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/records_unit \
  uv run pytest -q

# perf suite: a seeded database, measured instead of the SQLite file
RECORDS_PERF_N=20000 RECORDS_PERF_URL=postgresql+asyncpg://postgres@localhost:5432/records_perf \
  uv run pytest -q -s -m perf tests/perf
```

`SM_TEST_DATABASE_URL` is the repo-wide name — `pagebuilder` and `news` read
the same variable, through the same `tests/pg_support.py` at the repo root, so
one export runs all three suites on one database. **`RECORDS_TEST_URL` still
works** and is read as an alias when `SM_TEST_DATABASE_URL` is unset; the
Postgres CI job and the 2026-09-21 study both name it.

Create the databases first; neither variable creates one. The perf suite needs
permission to `CREATE DATABASE`, because the measurements that mutate their
database run against a `CREATE DATABASE ... TEMPLATE` copy and drop it
afterwards — the Postgres equivalent of the SQLite branch copying the file.

`tests/test_postgres_lock.py` runs **only** when `SM_TEST_DATABASE_URL` (or
its `RECORDS_TEST_URL` alias) names a Postgres database: it is the concurrency proof for the `SELECT ... FOR UPDATE`
branch of the per-type lock, which cannot be reached on SQLite.
`tests/test_unique_concurrency.py` and `tests/test_reindex_runner_locking.py`
are its counterparts and stay on a SQLite file whatever the variable says,
because what they pin is the other branch.

The e2e suite picks its database from `SM_DATABASE_URL`, which
`playwright.config.ts` passes through when it is set:

```bash
SM_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/records_e2e \
  npx playwright test tests/e2e/records-*.spec.ts
```

`tests/e2e/start-test-server.sh` empties whichever database that names —
deleting the file for SQLite, dropping and recreating the schema otherwise —
before running the migrations.

Results of the last full Postgres run are in
[`docs/postgres-2026-09-21.md`](docs/postgres-2026-09-21.md).


### Rebuilding the index by hand

The rebuild normally runs as a background task right after the schema change.
If a worker was restarted mid-way, the field stays in `reindex_pending` and
`/health/ready` degrades once an entry is older than
`reindex_stale_after_seconds`, naming the type and fields. Run it yourself
from the repo root:

```
python -m sm_records.cli reindex            # every type with pending keys
python -m sm_records.cli reindex --type KEY # one type
```

It is idempotent and resumable — index rows are derived from the stored
payloads, so running it twice converges.

### Subscribing to what records do

The module publishes domain events on the framework's bus, and subscribes to
nothing. A host handles them in its own `register_event_handlers`:

```python
from simple_module_core.events import EventBus
from sm_records.contracts.events import RecordTypeChanged, RecordUpdated


class MyModule(ModuleBase):
    def register_event_handlers(self, bus: EventBus, app=None) -> None:
        bus.subscribe(RecordUpdated, self.on_record_updated)
        bus.subscribe(RecordTypeChanged, self.on_type_changed)

    async def on_record_updated(self, event: RecordUpdated) -> None:
        # event.type_key, event.uuid, event.version, event.status_before/after
        ...
```

The set is `RecordCreated`, `RecordUpdated`, `RecordTrashed`,
`RecordRestored`, `RecordPurged`, `RecordTypeChanged` and `RecordTypeDeleted`
— see
[docs/architecture.md § Extension points](docs/architecture.md#extension-points)
for what each carries and why. Four properties are worth knowing before you
rely on them:

- **They arrive after the commit.** The write is already visible to any
  session by the time a handler runs, and a request that rolled back publishes
  nothing.
- **Bulk paths speak in records.** An import publishes one event per row that
  wrote (a dry run publishes none), a delete that cascades publishes one per
  record it reached — with `cascaded_from` naming the record the operator
  actually asked about — and deleting a type publishes one `RecordPurged` per
  record before the `RecordTypeDeleted`.
- **They carry identifiers, not payloads.** Read the record if you need its
  content. The exception is `RecordPurged`, which is the one event whose
  subject is gone — and even that one carries identity (`uuid`, `locale`,
  `translation_group`) rather than the payload, because a type delete is
  set-based and never instantiates the rows it removes.
- **Handler failures are the bus's business, not yours to be careful about.**
  `EventBus.publish` gathers with `return_exceptions=True` and logs; a
  subscriber that raises does not take the write down, and does not stop the
  other subscribers.

`RecordTypeChanged` is the one to reach for if you register an index or reduce
provider: `index_affecting_keys` names the fields whose stored shape just
moved, which is what the "run the CLI afterwards" note below is asking you to
notice by hand.

### Extending the index

The built-in projection writes one index row per field marked `indexed: true`.
An **index provider** is the seam for everything a schema cannot express — a
computed bucket, a normalised sort key, a value denormalised from a related
record. It is a callable `(record, record_type) -> Iterable[IndexEntry]`, and
the keys it declares as `VirtualField`s become filterable and sortable on
every type's records:

```python
from sm_records.index import IndexEntry, IndexKind, VirtualField, register_index_provider


def price_bucket(record, rtype):
    price = (record.data or {}).get("price")
    if price is not None:
        yield IndexEntry(IndexKind.NUMBER, "price_bucket", int(float(price)) // 100)


register_index_provider(price_bucket, fields=[VirtualField("price_bucket", IndexKind.NUMBER)])
```

`?filter=price_bucket:gte:1` and `?sort=-price_bucket` then work like any
declared indexed field: same operator matrix per kind, `many=True` for a key
that projects several rows per record (`eq` matches any of them, `ne` none of
them), and the same truncation re-check on text. Those six names, plus
`IndexProvider` (the callable's type, for annotating one) and `virtual_fields`
(every provider-projected key, by key), are the whole public surface of
`sm_records.index` — its `__all__`; the writer, the query builder and the
rebuild are internals.

Register at import time or from your module's `on_startup` — anywhere before
the first record is written. The registry is process-global, so every worker
must run the same registrations, and the built-in provider is always first and
cannot be removed.

A few consequences worth knowing before you use it:

- **A virtual key must be a field key, and one nothing else resolves first.**
  `register_index_provider` refuses a key that does not match
  `^[a-z][a-z0-9_]*$`, is over 64 characters, or names a record column or
  fixed filter column (`status`, `slug`, `position`, `created_at` …) — the
  query grammar resolves those before it ever looks at the registry, so such
  rows would be written on every save and never be readable. The refusal is a
  `ValueError` at registration: your code is what registers it, and there is a
  person reading the traceback.
- **A virtual key is global, so a type may not declare a field of the same
  key.** Saving a type with one is a 422 naming it. The type editor cannot
  grey the key out — what a host registered is not knowable to the browser —
  so a 422 on save is the contract. Registering a provider whose key collides
  with a field some type *already* declares is not retroactive: that type
  keeps working, its own definition wins the filter grammar, and the collision
  is logged once per type. (Taking a stored type offline because of a deploy
  elsewhere is not a trade this module makes.)
- **The rows must match what you declared.** An `IndexEntry` whose `kind`
  disagrees with the `VirtualField` registered for that key is dropped and
  logged once per provider and key, because it would land in a table no filter
  over that key reads — a key answering `is_null: true` for a record that has
  a value.
- **`REF` entries are load-bearing, and cannot be invented.** They are how
  `on_delete` is enforced and what the "what references this?" panel reads, so
  a `REF` entry naming a `target_type_id` that is not a record type is dropped
  too: a provider projects rows, it does not get to make unrelated records
  undeletable.
- **Changing what a provider projects does not mark anything.** A provider is
  code the host deploys, not a schema edit this module can see, so no
  `reindex_pending` entry appears and no filter is refused while the rows are
  stale. Run `python -m sm_records.cli reindex` after deploying a changed
  provider — or after registering a first one against existing records.
- **A provider that raises does not take the write down.** The failure is
  logged with the provider's qualified name and the record's uuid, that
  provider contributes no rows for that record, and the other providers and
  the write itself carry on. A broken host extension must not make every
  record unsaveable; its rows come back on the next reindex.

### Maintained aggregates

An index provider makes a record *queryable*; a **reduce provider** keeps a
running aggregate of the whole type, updated on every write. It is the answer
to one problem only — a `GROUP BY` over a type so large that the live
`/aggregate` above has become too slow — and it is opt-in per provider,
because it buys that speed with a second source of truth.

```python
from decimal import Decimal

from sm_records.index import ReduceSpec, register_reduce_provider

register_reduce_provider(
    ReduceSpec(
        key="orders_per_state",
        group_by=lambda record, rtype: (record.data or {}).get("ship_state"),
        value=lambda record, rtype: Decimal((record.data or {}).get("total") or 0),
        value_label="total",
    )
)
```

Read it back with `GET …/records/aggregate?reduce=orders_per_state`, which
returns the same shape as a live aggregate plus `stored: true` and
`updated_at` — so a caller can ask the same question both ways and compare.

**What `metric` says.** A live aggregate's `metric` echoes what you asked for,
and `sum:<x>` there names a **field**. A stored one has no field — it has your
`value` callable — so it reports the spec's own description: `"count"` when
the spec declares no `value`, `"sum:<value_label>"` when it declares one and
labels it, and the bare `"sum"` when it does not. `value_label` is free text
naming the quantity being folded; with `value_label="total"` above, both
readings of the example answer `metric: "sum:total"`, which is what makes the
two comparable at a glance.

**Delta, rebuild, verify.** The three exist together and none of them is
optional:

- **Delta.** `write_index` computes what the record contributed *before* the
  write and what it contributes after, and applies the difference with
  `UPDATE … SET count = count + :d` inside the same transaction. The database
  does the arithmetic, so two writers cannot both read `7` and both store `8`.
  On SQLite the per-type write lock already serialises them; on Postgres the
  row `UPDATE` does. An edit that does not move the record costs no statement
  at all, and an install with no spec registered costs exactly what it did
  before this existed.
- **Rebuild.** `python -m sm_records.cli reindex --type KEY` (and the reindex
  button, and any schema-triggered rebuild) throws the type's stored groups
  away and recomputes them from the records. The table is therefore never more
  than a cache of something the documents already say.
- **Verify.** `python -m sm_records.cli reindex --verify [--type KEY]`
  recomputes every spec and reports each `(type, key, group)` whose stored row
  disagrees. Exit code `1` on drift, `0` clean, so it works as a deploy gate
  or a cron check. Design §7.5's objection to a maintained aggregate was that
  it can drift; the answer is not that it cannot, it is that **drift is
  detectable**. A verify run *in this process* also degrades `/health/ready`
  with a `reduce_drift` detail until the next clean verify or rebuild; a CLI
  verify is a different process and reports on its own stdout instead.

The transitions, each of which has a test:

| event | what moves |
|---|---|
| create | `+1`, `+value` into the new group (insert on the group's first sight) |
| update, same group | `+new − old` on `sum` only; no count change |
| update, new group | `−1 −old` on the old group, `+1 +new` on the new one |
| soft delete (trash) | `−1 −value`; a trashed record is **not** counted |
| restore | `+1 +value` |
| purge of a trashed record | nothing — it was decremented when it was trashed |
| delete the type | every group of every spec on it is removed |

A group whose count reaches zero is deleted rather than left at zero, so the
table is exactly the set of non-empty groups — which is what makes it
comparable to a fresh recompute row for row.

Other things to know before you register one:

- **A reduce key is a virtual key.** Same rules as a `VirtualField`: it must
  match `^[a-z][a-z0-9_]*$`, may not name a record column or fixed filter
  column, has one owner, and is refused as a declared field key on save.
- **Registering a spec marks nothing.** A provider is code you deploy, not a
  schema edit this module can see, so no `reindex_pending` entry appears and
  the table simply has no rows for the new key. Run
  `python -m sm_records.cli reindex --type KEY` after deploying one, or after
  changing what an existing one folds on. Until then the live `/aggregate` is
  unaffected either way.
- **Every worker must run the same registrations.** The registry is
  process-global; a worker that skipped the registration writes no deltas, and
  what it writes goes missing from the stored aggregate until a rebuild.
- **`group_by` returning `None` means "no group"**, not an "unknown" bucket.
  `value` returning `None` means zero contribution — the record still counts.
- **Groups are stored as text, truncated at 512 characters**, which is the
  same cut `text` index values take. A spec grouping on free prose will merge
  groups that differ only after the cut; group on something bounded.
- **One row per group is the cost.** A spec whose group is effectively unique
  per record gives you a stored table as large as the type, maintained on
  every write, for no benefit. That is a design mistake no implementation here
  can fix.
- **A destructive schema change rebuilds them.** Discarding a deleted field's
  orphaned values rewrites every payload of the type, which is the one thing
  other than a record write that can move what a spec folds on — so that pass
  rebuilds the type's maintained aggregates before it returns.
- **A spec that raises contributes nothing and is logged.** The write itself
  is never taken down by a host's extension — but a failure on the *old* side
  of a delta leaves a group over-counted until the next rebuild, which is
  exactly what `--verify` is for.

### Demo data

`sm_records.seed` writes a small US-flavoured business dataset — five Record
Types (`company`, `contact`, `product`, `store`, `order`, with relations
between them) and however many records you ask for — through the real
services, so a seeded install has the same index rows, revisions and
relation checks a hand-built one would. Run it from the repo root:

```
python -m sm_records.cli seed                         # 5000 records, seed 42
python -m sm_records.cli seed --records 2000 --seed 7  # a smaller, different run
python -m sm_records.cli seed --reset                  # purge the demo types first
python -m sm_records.cli seed --database-url sqlite+aiosqlite:///path/to.db
```

On a host that declares the `events` [collection](#collections) the seeder adds
a sixth type, `event`, in that collection: a `datetime`, a `select` and a
`venue` relation pointing at the **global** `store` type, so the demo dataset
exercises a relation across a collection boundary. On a host that declares no
collection the type is skipped entirely and the dataset is exactly what it
always was.

`--records` is the *total* across all the types (roughly 5% company / 25%
contact / 15% product / 45% order / 10% store, minimum one each; `event` takes
5% proportionally from the five where it exists, so `--records N` still means
N). It is
deterministic for a given `--seed`; re-running without `--reset` tops up the
dataset with more records, and unique fields (`contact.email`, `product.sku`,
`order.order_no`) stay collision-free because their values are keyed off each
type's current record count, not the seed alone. `--reset` hard-deletes the
demo types and everything in them (including the trash) before reseeding.

On an install with more than one `content_locale`, the seeder also marks the
`company` type `translatable` and gives roughly a tenth of the companies a
sibling in the second locale, so a multilingual host has something for the
Languages panel and for `?locale=` to show. On a single-locale install it does
none of that and writes exactly the dataset it always did.

Every record goes through `services.records.create_record`, so this is the
slow path, not a bulk insert — 10,000 records took **1 minute 46 seconds
(94 records/s)** on SQLite in testing, and the rate no longer falls away as
the dataset grows now that the `unique` check is an existence test rather
than a `COUNT` over the whole type (see [docs/performance.md](docs/performance.md)).
The run finishes with one `ANALYZE` pass over the module's own tables: a bulk
load is exactly the state SQLite has no planner statistics for, and a seeded
database's first act is to be queried. For an in-process caller (a test, a
perf harness) that already has a `db_state`/`settings` pair, call
`sm_records.seed.seed_database(db_state, settings, records=..., seed=...,
reset=...)` directly instead of shelling out.

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
