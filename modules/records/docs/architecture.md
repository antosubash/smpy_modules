# Records — architecture

For developers changing or extending the module: a map of where things are and
which rules are load-bearing. The *reasoning* lives in the design docs, and the
section numbers cited below (as the code cites them) are theirs —
[the original design](../../../docs/plans/2026-09-19-records-module-design.md)
(§4–5 storage, §6 field types, §7 the index layer, §8 schema evolution, §9
relations, §10 permissions and the public API) and
[Phase 5](../../../docs/plans/2026-09-20-records-phase5-design.md) (§1 paging,
§2 import/export, §4 content i18n, §5 aggregates, §6 collections).

## The document/index split

Modeled on [YesSql](https://github.com/sebastienros/yessql) and the content
layer Orchard Core builds on it. **No table is ever created at runtime.**

- `records_type` — one row per Record Type. `fields` is a JSON list of field
  definitions. `version` bumps on every write (optimistic concurrency);
  `schema_version` only when a change affects payloads.
- `records_record` — the document table. `data` is the payload, and **it is
  never queried**: no JSON extraction, no `LIKE` over a payload. Beside it sit
  the *fixed columns* every record has whatever its type declares — `status`,
  `display_title`, `slug`, `locale`, `position`, `published_at`, `created_at`,
  `updated_at` — the module's `ContentItemIndex`, filterable and sortable with
  no index table at all.
- `records_revision`, `records_type_revision` — append-only history, record
  revisions pruned to `revision_limit`.
- Six index tables, one per value kind (§7.3), each carrying `record_id`,
  `type_id`, `field_key` and one typed value column:

  | Table | Value column | Holds |
  |---|---|---|
  | `records_index_text` | `value str(512)` indexed + `value_full Text` | `text`, `select`, `multiselect`, `email`, `url` |
  | `records_index_number` | `value Numeric(19, 5)` | `number`, `integer` |
  | `records_index_bool` | `value Boolean` | `boolean` |
  | `records_index_date` | `value Date` | `date` |
  | `records_index_datetime` | `value DateTime(tz)` | `datetime` |
  | `records_index_ref` | `target_uuid` + `target_type_id` | `relation` |

- `records_index_reduce` — the one *fold* table, keyed by `(type_id, key,
  group)`. Global, never per-collection: a reduce row has no `record_id`.

**Index rows carry no record state** — no `status`, no `is_deleted`. Every query
selects the `Record` entity and joins index rows by primary key, and that join
applies `status`, the framework's soft-delete filter and any future tenant
filter for free. Mirroring the flags would mean an `UPDATE` across N rows on
every publish, trash and restore.

Two consequences of the text split (§7.4) are easy to get wrong. An `eq` must
match `value` **and** re-check `value_full` — `value_full IS NULL` is itself the
assertion that the column holds the whole string, so two values differing only
after character 512 are otherwise indistinguishable. And `starts_with` compiles
to a half-open range, not `LIKE 'x%'`, because the LIKE optimization needs a
`NOCASE` index on SQLite and every index here is `BINARY`; hence its
case-sensitivity.

### The semi-join

A filter term is **not** a correlated `EXISTS` per record. It compiles to
`records_record.id IN (SELECT record_id FROM records_index_text WHERE type_id =
:t AND field_key = :k AND <value predicate>)` — a semi-join the planner can
drive from the index. `ne` negates the *whole* semi-join ("no value equals x"),
the only correct reading for a multi-valued field; `eq` on the same field is the
"any" reading. `is_null` is the negation of the semi-join with no value
predicate at all.

`index/query.py` is the façade; beside it are `_filters` (which records match),
`_sorting` (in what order, and the `LEFT JOIN` aliases that produce it),
`_cursor` (keyset encode/decode and the sort signature), `_fixed` (the fixed
columns) and `_predicates` (the per-kind value SQL).

### Table sets

Since Phase 5 §6 the query layer is parameterized by a `TableSet`.
`tables_for(rtype)` returns the global set, or a collection's identical-shaped
copy built by the same factories with the prefix `records_c_<name>_`. A
collection is declared in code before `create_app`
(`collections.declare_collection`), because the tables have to exist in the
host's Alembic history. With none declared, `tables_for` always returns the
global set and the query layer runs the statements it always did.

## How a schema change is classified and applied

`schema/diff.py` diffs the stored `fields` against the proposal and produces a
`SchemaDiff` of `SchemaChange`s, each carrying a `ChangeClass`. The class of the
whole diff is the **most severe** change in it (§8.2):

| Class | Trigger | Applied |
|---|---|---|
| `additive` | New optional field, new choice, relaxed constraint, label edit | Immediately |
| `index_affecting` | `indexed` toggled, an indexed field retyped, a relation re-pointed or `many` flipped, `display_field` changed | Immediately, plus a `reindex_pending` marker; the field refuses filters (409) until the rebuild clears it |
| `restrictive` | New required field, narrowed type, tightened constraint, removed choice, newly unique field | Only after a clean dry run, or under `force` |
| `destructive` | Field removed | Values move to `_orphaned` on each record's next write |

`services/schema_change.py` has three entry points on one pipeline: `preview`
classifies and dry-runs and writes nothing; `apply` **re-runs** the
classification and then writes; `rollback` replays an earlier
`RecordTypeRevision` through `apply`, so an undo is refusable like any other
change. Re-running rather than trusting a report id is the rule (§8.9): a report
taken minutes ago describes a different database. The one exception is
`_preview.reused_report`, which reuses a completed job's report when it was
taken against the same type, the same proposed fields **and the same
`RecordType.version`** — which the save has already checked under the type's row
lock — within `preview_job_ttl_seconds`.

**The payload never migrates here.** A forced restrictive change leaves failing
rows exactly as they were — *marked*, not mutated and not hidden. The only bulk
rewrite the module ever does is the `_orphaned` sub-key on an explicit
`discard`; the index is derived and rebuilt out of request. Field keys are
immutable: a rename decomposes into remove-then-add and is classified as both.

**Newly unique is the one restrictive class a payload scan cannot see.** The dry
run validates one record at a time; duplication is a property of a *pair*. So
`services/_duplicates.py` runs alongside it — one `GROUP BY … HAVING` per key
against the index table for a field that is already indexed, and a collector
riding on the dry run's own walk for one gaining `unique` and `indexed`
together — and folds its count into `DryRunReport.failing` plus a per-key
`duplicates` map. Two records in the same `translation_group` are not
duplicates of each other, because `_claims.ensure_unique` exempts siblings.
`force` is still the escape hatch, but it is the one restrictive class it does
not leave *recoverable*: every other marked record is fixed by its next
ordinary write, and a duplicate cannot be. Such a record is marked on the
single-record read (`_duplicates.conflicts_for` tops up `invalid`) and stays
saveable for any write that leaves the contested value alone — `ensure_unique`
does not make a write re-claim a value the row already holds.

## The services layer

`services/` is the domain. Two rules hold everywhere:

1. **Services never import FastAPI.** They raise `services.errors.RecordsError`
   subclasses carrying a `status_code`; `endpoints/api/_errors.RecordsErrorRoute`
   — a custom `APIRoute` scoped to this package's routers — maps them to JSON. A
   service raising `HTTPException` would be unusable from the CLI, from a
   background task and from another module.
2. **Services never commit.** `get_db` owns the request's transaction; flush if
   you need DB-assigned values. Exactly two callers commit, and both say why in
   their docstring: `cli_io` (no request exists) and `services/reindex_runner`
   (a deferred job has no `get_db`).

Because the error route turns an exception into a *response* inside the handler,
`get_db` never sees it and would commit whatever the refused call already wrote.
Every error path therefore rolls the session back explicitly and clears the
has-writes flag — which is what makes `on_error=abort` and a refused cascading
delete mean *nothing was written*.

Endpoints may resolve dependencies, parse the query grammar, call services,
serialize contracts and schedule deferred jobs. They may not build SQL, commit
or decide domain rules. The one thing an endpoint does that a service cannot is
`menu.mark_dirty(app)`: a service takes a session and knows nothing about the app.

`deferred.py` is the module's own ASGI middleware for post-response work — not
`BackgroundTasks`, which runs inside the scheduling request's dependency
teardown and therefore inside its still-open transaction (on SQLite, a deadlock
broken by `database is locked`).

## Extension points

Everything a host can plug in is `sm_records.index.__all__`: `IndexEntry`,
`IndexKind`, `IndexProvider`, `ReduceSpec`, `VirtualField`,
`register_index_provider`, `register_reduce_provider`, `virtual_fields`. The
writer, the query builder and the rebuild are internals.

**Index providers** (§7.6) are the seam for anything a schema cannot express — a
computed bucket, a normalized sort key, a value denormalized from a relation. A
provider is `(record, record_type) -> Iterable[IndexEntry]`; the keys it declares
as `VirtualField`s become filterable and sortable on every type, with the same
operator matrix per kind.

Load-bearing constraints: a virtual key must look like a field key and must not
name a record or fixed column (a `ValueError` at registration); a type may not
declare a field of the same key (422 on save, never retroactive); an
`IndexEntry` whose kind disagrees with its `VirtualField` is dropped and logged;
a `REF` entry naming a non-type is dropped, since `REF` rows are what
`on_delete` reads; and a provider that raises is logged, contributes nothing,
and does not take the write down.

**Reduce providers** (Phase 5 §5.2) keep a maintained aggregate, applied as a
delta inside the write (`UPDATE … SET count = count + :d`, so the database does
the arithmetic). They exist together with a rebuild and a verify, and none of
the three is optional: the answer to "a maintained aggregate can drift" is not
that it cannot, but that drift is **detectable**.

**Collections** (`declare_collection`) give a type its own table set. Both they
and the public routes are wired from `on_startup`, not the construction hooks,
because both depend on settings hydrated at lifespan start.

**Domain events** (`contracts/events.py`) are the subscribe-only seam: the
module publishes, and a host handles them in its own
`register_event_handlers(bus, app=...)`. They are dataclasses because the
framework's `Event` base is one (`simple_module_core.events`), not because
this module departs from the repo's SQLModel rule.

| Event | Published by | Carries |
|---|---|---|
| `RecordCreated` | `POST /records`, `POST …/translations`, each import row that created | `type_key`, `uuid`, `locale`, `translation_group`, `status` |
| `RecordUpdated` | `PUT /records/{uuid}`, a revision restore, each import row that updated | `type_key`, `uuid`, `version`, `status_before`, `status_after` |
| `RecordTrashed` | `DELETE /records/{uuid}` — one per record the delete reached | `type_key`, `uuid`, `cascaded_from` |
| `RecordRestored` | `POST …/restore` | `type_key`, `uuid` |
| `RecordPurged` | `DELETE …/purge`, and one per record of a deleted type | `type_key`, `uuid`, `locale`, `translation_group` |
| `RecordTypeChanged` | `PUT /types/{key}`, a schema rollback, a `mode=update` type import | `type_key`, `schema_version`, `kind`, `index_affecting_keys` |
| `RecordTypeDeleted` | `DELETE /types/{key}` | `type_key`, `purged` |

Three decisions are worth the sentence they cost. **Publishing is a status
transition, not its own event**: `RecordUpdated` carries the status pair rather
than there being a `RecordPublished`, which would double-fire on a
create-as-published. **`cascaded_from` exists because a delete reaches records
of types the URL never named** (§9's `cascade`), and no subscriber could
reconstruct which. **`RecordPurged` is the only event that has to be complete
in itself**, because it is the only one whose subject cannot be read back.

They are published **from the endpoint, after the commit**: services never
import FastAPI and the bus arrives on `app.state`, so the seam is the one
`menu.mark_dirty` already uses — and `sm_records/deferred.py` is what makes it
after the commit, so a subscriber never sees an event for a write that rolled
back. Bulk paths emit per record: an import publishes one event per row that
wrote (a dry run publishes none), a cascade one per record trashed, a type
delete one `RecordPurged` per record and then the `RecordTypeDeleted`. A host
with no subscribers pays an `EventBus.publish` that returns before gathering
anything.

`RecordTypeChanged` is what makes `register_reduce_provider`'s "run the CLI
afterwards" caveat automatable: `index_affecting_keys` names the fields whose
stored shape just moved, so a provider knows its projection is stale without
diffing anything itself.

## The wire contracts

`contracts/` is the only thing endpoints serialize, split by subject: `schemas`
(types and records), `relations`, `revisions`, `schema_change`, `io`,
`aggregate`, `public`, `i18n`, `_types`. They are SQLModel classes — plain
`SQLModel` for DTOs, `table=True` only for real tables; never Pydantic
`BaseModel`, never SQLAlchemy `DeclarativeBase`.

`contracts/public.py` is deliberately a *separate* shape rather than a filtered
`RecordRead`: the fields an anonymous caller must not see are removed from the
shape, and `PUBLIC_FIXED_COLUMNS` is derived from `FIXED_COLUMNS` so a column
renamed out of the record row cannot survive in the public grammar.

**API-version contract.** `ModuleMeta.requires_framework` declares which
`simple_module_core` versions the module supports (`>=1.0,<2.0` — the framework
*API* version, decoupled from the framework *package* version). Update it on
each framework major bump, after verifying compatibility; Python dependencies
use ranges, never `==`. The module's own HTTP contract is versioned by
convention rather than by a URL segment: `/api/*` is a separate contract from
the view routes and does not move when screens do.

## The test harness

`modules/records/tests/` runs from inside the module (its own pytest config) and
needs no host.

- **`app_harness.py`** builds a real app by calling the module's own
  `register_*` hooks — never by re-implementing them — over in-memory SQLite,
  and yields an `httpx.AsyncClient`. `records_app` and `client` are the
  fixtures; `seed_type` / `seed_record` write on a committed session of their own
  so a request sees them.
- **`X-Test-Roles: role-a,role-b`** selects the caller's roles **per request**,
  because an `allowed_roles` test needs the same type seen by two callers inside
  one test. No header at all is the stand-in for an anonymous caller — how the
  public-API tests are written. The fixed cast is `ROLE_VIEWER`, `ROLE_EDITOR`,
  `ROLE_EDITOR_TWO`, `ROLE_MANAGER`, `ROLE_NONE` and `ADMIN` (the wildcard).
- **`collections_harness.py`** does the same for a declared collection.
- **`tests/perf/`** is behind the `perf` marker and excluded from the default
  run. It asserts *shapes* — "a filtered list does not full-scan
  `records_record`", "a page costs a constant number of statements",
  "`total=false` costs one statement less" — never wall-clock thresholds, and
  prints a results table plus each operation's heaviest query plan.
  `RECORDS_PERF_N`, `RECORDS_PERF_REPS`, `RECORDS_PERF_BUDGET`,
  `RECORDS_PERF_DB` and `RECORDS_PERF_URL` configure it. See
  [operations.md](operations.md#performance-headlines) for how to run it.

Run it with `cd modules/records && ../../.venv/bin/python -m pytest -q`.

## File layout

Every `.py`/`.ts`/`.tsx` is under 300 lines with no exemptions, so most subjects
are a small package rather than one module; each `__init__` or façade names its
own seams.

```
sm_records/
├── module.py        RecordsModule and its register_* hooks
├── boot.py          mounts + exempts the public router, from on_startup
├── constants.py     every route, permission and limit as a named constant
├── settings.py      RecordsSettings (DB-backed) + settings_checks.py
├── deps.py          permissions, allowed_roles narrowing, request session
├── _grammar.py      ?filter= / ?sort= / ?expand= / ?after= parsing
├── menu.py          per-type sidebar entries (+ _menu_middleware.py)
├── health.py        the records.reindex check
├── deferred.py      post-response job middleware
├── collections.py, locales.py, puck-blocks.ts
├── cli.py           + cli_io.py, cli_verify.py
├── models/          tables, per-table-set factories
├── schema/          field definitions, the compiler, the diff and its classes
├── index/           query building, writing, reindex, reduce, providers
├── services/        the domain; raises RecordsError, never commits
├── contracts/       wire DTOs
├── endpoints/       api/* (JSON) and views*.py (Inertia)
├── seed/            the demo dataset
├── pages/*.tsx      auto-discovered Inertia pages — nothing else goes here
├── components/      everything extracted out of a page (+ hooks/, utils/)
└── locales/en.json  every user-visible string
```

**Never add a file under `pages/` that is not a real Inertia page**: the page
name is derived from that path by `import.meta.glob`, so a stray `.tsx`
silently registers a page. Extractions go to `components/`, `hooks/`, `utils/`.
