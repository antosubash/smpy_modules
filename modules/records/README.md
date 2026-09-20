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
downgrade to the revision *before* the records one, or drop the ten
`records_*` tables directly.

## Usage

Go to **Record Types** in the admin sidebar (`/admin/records`) to define a
type and its fields. Each type gets a generic, schema-driven list screen and
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
secret, and it carries a digest of the sort it was produced under. Three
things are a `400`: a cursor that does not decode, a cursor replayed under a
different `?sort=` or against the trash, and `?page=` and `?after=` sent
together — they are two ways of asking for a page and the server will not
guess which one you meant. `?page=` stays for the admin UI, which shows
numbered pages.

A full final page still returns a `next_cursor`; the request after it comes
back empty with `next_cursor: null`. That is one extra round trip at the end
of a walk and is the ordinary contract of cursor pagination — "fewer rows than
asked for" is the only end-of-data signal that survives a capped `total`.

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
| `default_page_size` | 25 | no |
| `max_page_size` | 200 | no |
| `revision_limit` | 50 per record | no |
| `max_payload_bytes` | 262144 (256 KB) | no |
| `max_count` | 10000 | no |
| `preview_sync_limit` | 5000 | no |
| `preview_job_ttl_seconds` | 600 (10 min) | no |
| `max_import_bytes` | 52428800 (50 MB) | no |
| `max_fields_per_type` | 100 | no |
| `max_indexed_fields_per_type` | 25 | no |
| `reindex_batch_size` | 500 | no |
| `reindex_stale_after_seconds` | 900 (15 min) | no |

`max_count` is how far a list page's `total` is counted exactly — see
[Paging a large type](#paging-a-large-type). `preview_sync_limit` is the
largest type a schema preview will dry-run inside the request, and
`preview_job_ttl_seconds` is how long a finished preview's report stays
reusable by the save that follows it — see
[Changing a schema that already holds records](#changing-a-schema-that-already-holds-records).

`public_route_prefix` is the one setting a change to needs a restart. The
routes it configures are mounted — and exempted from authentication — while
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
  walking pages cannot locate the hidden ones.

## Public read API

Off by default and per type. Setting `is_public` on a Record Type serves its
published records anonymously at two routes, under `public_route_prefix`
(default `/api/records/public`):

| route | answers |
|---|---|
| `GET`/`HEAD` `{prefix}/{type_key}` | `{items, total, total_capped, page, page_size, next_cursor}` |
| `GET`/`HEAD` `{prefix}/{type_key}/{uuid}` | one record |

A record reads back as `uuid`, `slug`, `display_title`, `published_at` and
`data` — nothing else. The audit columns, `version`, `status`, `invalid` and
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
- **No `?expand=`** — an anonymous caller must not be able to turn one request
  into a batch of joins against other types, some of which may not be public.
  `expand` and `trashed` are simply not parameters here; unknown ones are
  ignored.
- `page_size` is clamped to `max_page_size` rather than refused.
- **`?after=`, `?total=false` and the `max_count` bound apply here too** — see
  [Paging a large type](#paging-a-large-type). A client walking a large public
  type is precisely the caller that should not be paying for an `OFFSET` and a
  count it never reads.

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

Two things stay visible, and both are about the schema rather than the
records: `GET /api/records/types/{key}` and the type editor at
`/admin/records/types/{key}`, which need `records.manage_types`. A manager
locked out of the screen that edits `allowed_roles` would be a one-way door.

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
  `schema_version`, `version`, `status`, `slug`, `display_title`, `position`,
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
  field is checked with a `SELECT ... LIMIT 1` inside the write's transaction,
  and writes to the type are serialized to close the check-then-act race
  between two concurrent creates: a row lock on the type on Postgres, and a
  write against the type row — which takes SQLite's `RESERVED` lock — on
  SQLite, where `FOR UPDATE` locks nothing. This is "unique enforced at the
  cost of serializing writes on that type," not a database-level uniqueness
  guarantee.

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
  field's type, or changing `display_field`) applies immediately and
  enqueues a rebuild: the field appears in the type's `reindex_pending` and
  refuses filters and sorts until the rebuild has moved its rows and cleared
  the entry. The rebuild runs as a background task after the request.
- `slug_field` changes never regenerate existing slugs — a slug is an
  address, and regenerating could break links or collide with a slug handed
  out since. Only records written after the change use the new pointer.

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
| `GET /api/records/types/{key}/records/export?format=json\|csv` | `records.view` | streaming; takes the list screen's `filter`/`sort`, and `trashed=true` (which costs `records.edit`) |
| `POST /api/records/types/{key}/records/import` | `records.edit` | multipart `file=`, or a raw body with `Content-Type: application/json` / `text/csv` |
| `GET /api/records/types/{key}/export` | `records.view` | the type definition alone, shaped for the route below |
| `POST /api/records/types/import` | `records.manage_types` | `mode=create` (default) or `mode=update` + `expected_version` |

The record export **streams**. It walks the type keyset-paged by `id` in
batches of `reindex_batch_size`, on a session of its own, so a 100k-record
type is exported in constant memory rather than assembled in one list. (An
export with an explicit `?sort=` cannot be keyset-paged — the sort key lives
in an index table — and pages by `OFFSET` instead; it is meant for exporting a
*selection*, and the unsorted default is what a round trip should use.)

**What travels.** Each record carries `uuid`, `slug`, `status`, `position`,
`published_at` and `data`; `data` is the lenient read, so defaults are filled
in and a record stamped at an older schema version exports under the current
one. Relations travel as stored (`{"type": …, "uuid": …}`), never expanded.
The reserved `_orphaned` key, the audit columns, `version` and `is_deleted` do
not travel: they describe this install's copy of the row. `uuid` does, which
is what makes a round trip independent of autoincrement.

**CSV.** Columns are `uuid, slug, status, position, published_at` and then one
per declared field in declaration order; import is header-driven, so order and
missing columns are fine (a missing column means "leave it alone", an empty
cell means null). Values use the module's own wire forms — a `number` is its
decimal string, a boolean is `true`/`false`, a date is ISO. `multiselect`,
`json` and `media` cells are JSON-encoded; a relation is `type:uuid`, and a
to-many relation a JSON list of those. UTF-8 with **no** BOM, `\r\n` line
endings per RFC 4180.

> **No CSV formula-injection mitigation is applied**, deliberately. A cell
> beginning `=`, `+`, `-` or `@` is written verbatim rather than prefixed with
> an apostrophe. The prefix is not lossless — an importer cannot tell it from
> a value that genuinely starts with one — and these files are meant to round
> trip. Treat an export from an untrusted source the way you would any other
> CSV before opening it in a spreadsheet.

**Import options** (query string, or multipart form fields, which win):

- `dry_run` — **`true` by default.** A dry run parses, validates and matches
  every row and returns the full report, writing nothing.
- `mode` — `upsert` (default; match, else create), `create`, `update`.
- `on_error` — `abort` (default) is all-or-nothing: the request's transaction
  is rolled back and the 422 carries the report. `skip` writes the valid rows,
  each under its own savepoint, and reports the rest.
- `match_by` — `uuid` (default), `slug`, or the key of a **`unique`** field.
  Matching on a non-unique field is refused rather than resolved arbitrarily.
- `force` — an update whose row carries no `version` is refused, because the
  export deliberately does not carry one; `force=true` accepts last-write-wins.
- `max_import_bytes` (a setting, 50 MB by default) refuses a larger body with
  `413` **before** parsing it.

The report is `{dry_run, mode, total, created, updated, skipped, failed,
errors: [{row, uuid, field, message}], errors_truncated, duration_ms}`, with
`created + updated + skipped + failed == total` and at most 200 errors listed.
**`skipped` is why re-importing an export is a no-op**: a row the record
already agrees with is not written at all, so versions do not move.

A row is refused for carrying `_orphaned`, naming an unknown field, pointing
at a relation target that does not exist, repeating a `uuid` already used
earlier in the same file, naming a `uuid` that belongs to another type, or
matching a record in the trash (restore or purge it first).

**Type definitions.** `POST /api/records/types/import` with `mode=update` and
an `expected_version` routes through the ordinary `update_type` path, so
importing a definition onto a populated type is classified, dry-run and
refused with the same report — and answered with the same `force` /
`orphaned` — as the same change made in the schema editor.

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
them), and the same truncation re-check on text. Those six names are the whole
public surface of `sm_records.index`; the writer, the query builder and the
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

### Demo data

`sm_records.seed` writes a small US-flavoured business dataset — five Record
Types (`company`, `contact`, `product`, `store`, `order`, with relations
between them) and however many records you ask for — through the real
services, so a seeded install has the same index rows, revisions and
relation checks a hand-built one would. Run it from the repo root:

```
python -m sm_records.cli seed                         # 5000 records, seed 42
python -m sm_records.cli seed --records 2000 --seed 7  # a smaller, different run
python -m sm_records.cli seed --reset                  # purge the five demo types first
python -m sm_records.cli seed --database-url sqlite+aiosqlite:///path/to.db
```

`--records` is the *total* across all five types (roughly 5% company / 25%
contact / 15% product / 45% order / 10% store, minimum one each). It is
deterministic for a given `--seed`; re-running without `--reset` tops up the
dataset with more records, and unique fields (`contact.email`, `product.sku`,
`order.order_no`) stay collision-free because their values are keyed off each
type's current record count, not the seed alone. `--reset` hard-deletes the
five types and everything in them (including the trash) before reseeding.

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
