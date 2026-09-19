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
route on it requires a session and one of the three permissions below — there
is no anonymous surface yet.

**`is_public` and `public_route_prefix` are stored but inert.** The public
read API they configure is **Phase 4** of the design doc (§16, "Phase 4 —
reach") and has not shipped: a type marked `is_public` is readable by exactly
the callers a private one is, and nothing reads `public_route_prefix`. The
flag is persisted and editable so the schema does not have to change when the
API lands. Two more §9/§10 features are Phase 4 with it: `?expand=` on a read
(depth-1 resolution of a relation, ignored today) and the `dangling: true`
marker on a reference whose target has been trashed or purged (a reference
like that reads back as the raw stored object).

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
| `public_route_prefix` | `/api/records/public` | yes — but see below |
| `default_page_size` | 25 | no |
| `max_page_size` | 200 | no |
| `revision_limit` | 50 per record | no |
| `max_payload_bytes` | 262144 (256 KB) | no |
| `max_fields_per_type` | 100 | no |
| `max_indexed_fields_per_type` | 25 | no |
| `reindex_batch_size` | 500 | no |
| `reindex_stale_after_seconds` | 900 (15 min) | no |

`public_route_prefix` is read by nothing: it configures the Phase 4 public
read API described under Usage, which has not shipped. Setting it changes no
behaviour.

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
