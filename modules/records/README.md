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

The same operations are available as a JSON API under `/api/records`, and a
type marked `is_public` additionally exposes an anonymous, published-only
read API (see Permissions below).

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
reported as a `restrict` blocker — for a caller the list excludes.

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
- **`unique` is enforced by the application, not by a database constraint.**
  The index tables are shared across every field of a kind, so a partial
  unique index naming a runtime-chosen field key isn't possible. A `unique`
  field is checked with a `SELECT` inside the write's transaction, and writes
  to a type with any unique field are serialized (a row lock on the type)
  to close the check-then-act race between two concurrent creates. This is
  "unique enforced at the cost of serializing writes on that type," not a
  database-level uniqueness guarantee.

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

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
