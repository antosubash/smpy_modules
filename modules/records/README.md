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
| `max_fields_per_type` | 100 | no |
| `max_indexed_fields_per_type` | 25 | no |
| `reindex_batch_size` | 500 | no |
| `reindex_stale_after_seconds` | 900 (15 min) | no |

`public_route_prefix` is the one setting a change to needs a restart. The
routes it configures are mounted — and exempted from authentication — while
the app boots, because the prefix only exists as the operator set it once the
host has hydrated these settings from the database.

## Relations

A `relation` field stores `{"type": "<type_key>", "uuid": "<record uuid>"}` —
and a row in the reference index, which is what makes both directions cheap.

**Forward: `?expand=`.** `GET /api/records/types/{key}/records` and
`…/records/{uuid}` take `?expand=field_a,field_b` and resolve those relation
fields to **depth one**, one batched query per named field for the whole page.
Each reference comes back under `expanded[field_key]`, in payload order, in
exactly one of three states:

- **resolved** — `display_title`, `slug` and `status` are filled;
- **dangling** — the target is in the trash or gone; `display_title` is
  `null`. A restorable delete must not break what references it, so this is a
  flag rather than an error or a dropped entry;
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
them). A referrer whose type the caller may not view is **counted in `total`
and omitted from `items`** — the count stays honest, because it is the count a
`restrict` refusal will produce, and the row itself does not leak.

## Public read API

Off by default and per type. Setting `is_public` on a Record Type serves its
published records anonymously at two routes, under `public_route_prefix`
(default `/api/records/public`):

| route | answers |
|---|---|
| `GET`/`HEAD` `{prefix}/{type_key}` | `{items, total, page, page_size}` |
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
- **The filter and sort grammar is the admin one, over indexed fields only.**
  A filter or sort naming a field that is unindexed, non-existent, or
  mid-reindex is a `400` naming the field — never the admin API's `409`:
  "cannot" and "cannot right now" are the same answer to a caller who has no
  business seeing operational state.
- **No `?expand=`** — an anonymous caller must not be able to turn one request
  into a batch of joins against other types, some of which may not be public.
  `expand` and `trashed` are simply not parameters here; unknown ones are
  ignored.
- `page_size` is clamped to `max_page_size` rather than refused.

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
the `admin` wildcard is refused writes on a type whose `allowed_roles` is
non-empty unless `admin` is one of the roles listed. So an admin creating a
restricted type must list a role they actually hold, or else use
`records.manage_types` to edit `allowed_roles` back before they can write its
records. The same list also governs what a delete elsewhere may do to this
type's records: a `cascade` or `set_null` relation pointing here is refused —
reported as a `restrict` blocker — for a caller the list excludes, and
`DELETE /api/records/types/{key}` (which purges every record of the type,
trash included) and an `orphaned: "discard"` schema edit are refused for them
too, `records.manage_types` notwithstanding.

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
- **`allowed_roles` narrows reads as well as writes, but it narrows them
  differently.** A caller the list excludes is *refused* a write and is
  *redacted* on a read: an expanded reference to such a type comes back
  `restricted`, and a referrer of one is counted without being listed. Neither
  is an error, because in both cases the caller is reading a record they are
  entitled to see that happens to point somewhere they are not.
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

Field keys are immutable: a "rename" is a remove plus an add, and is
treated as one. Every schema change writes a type revision;
`POST /api/records/types/{key}/revisions/{version}/restore` rolls back
through the same pipeline, so a rollback that would fail records is refused
like any other change.

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

- **A virtual key is global, so it is reserved.** Every type's records are
  queryable by it, and a type declaring a field of the same key would shadow
  it — so `validate_fields` refuses that key with a 422 naming it. The type
  editor cannot grey the key out: what a host registered is not knowable to
  the browser, and the key list it mirrors is static per process. A 422 on
  save is the contract. (A key that collides with a record column or a fixed
  filter column — `status`, `slug`, `created_at` … — is shadowed by that
  column instead and never queryable; don't name one that.)
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
