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
  `updated_at` and `invalid_since` — the module's `ContentItemIndex`,
  filterable and sortable with no index table at all. `invalid_since` is the
  one whose grammar name differs from its column (`invalid`, a boolean over
  it); `index/_fixed._FIXED_ALIAS` is where the two meet.
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

**Index rows carry no record state** — no `status`, no `is_deleted`, no
`tenant_id`. Every query selects the `Record` entity and joins index rows by
primary key, and that join applies `status`, the framework's soft-delete filter
and its tenant filter for free. Mirroring the flags would mean an `UPDATE`
across N rows on every publish, trash and restore.

**Tenancy lives on the owned rows only** (design
`docs/plans/2026-09-23-records-multitenancy.md` §B): `records_type`,
`records_type_revision` and each table set's `_record` and `_revision` carry the
framework's `MultiTenantMixin`; the index and reduce tables do not. A record's
`(type_id, tenant_id)` is a foreign key to `records_type (id, tenant_id)`, so
its tenant is always its type's — which makes every `type_id`-led index, unique
constraint and index row per-tenant without a column of its own. Type keys are
unique per tenant, and so are record uuids.

**Which tenant a request runs in is bound by the routers, not the framework**
(`sm_records/tenancy.py`). The admin API, the views and the public API each
carry a yield dependency — `bind_admin` or `bind_public` — as their *first*
dependency, so it is entered before `get_db` and still bound when `get_db`
commits on the way out. A single-tenant host (no `TenantMiddleware`) binds
`default`; a multi-tenant one binds the user's own tenant or refuses with
`tenant_required`, and the public API binds the framework-resolved tenant or
answers its `404`. A guard installed on the host's session class at startup
turns any records ORM statement or flush with no tenant bound into
`TenantUnbound`, because the framework's own answer to that is every tenant's
rows. It sees ORM statements only, so every Core statement, `UPDATE`/`DELETE`
and `IN`-subquery over an owned table carries an explicit `tenant_id`
predicate, and so does every natural-key lookup (type key, uuid, slug, the
public reads, an import's match) — design §E. Two tests keep that true: the
**statement census** (`tests/census.py`, on by default when the suite runs on
Postgres) fails any test in which `sm_records` sent a statement naming an owned
table without `tenant_id`, and the **isolation matrix**
(`tests/test_tenancy_isolation*.py`) proves, route by route, that a caller in
one tenant gets exactly an unknown key's answer for another tenant's rows. A
new route fails the matrix until it has a case.

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

### What "marked" means, and where the mark lives

Two representations of one fact, and neither replaces the other.

*Derived.* `services._payload.read_view` runs the compiled validator on read
and returns `invalid`, a list of `{field, message}`. It is the authority for
the record being edited and it costs a validator pass, which is why
`record_list_read` passes `with_invalid=False` and every list row's `invalid`
is `[]`.

*Stored.* `Record.invalid_since`, a nullable timestamp, written and cleared by
`services/_invalid.py`. Three rules, all stated there:

- **written only by a scan of the schema records are stored against** — the
  inline pass of a forced `apply`, and the `rescan` behind "Check records".
  Never by a draft preview, whose model is a proposal that may never be saved;
- **cleared by the record's next successful write** (create, update, import —
  that write validated against the current schema), and by a scan that finds
  the record clean. A restore is **not** one of them: it writes the row
  without looking at the payload, so it fixes nothing and the mark stays;
- **the timestamp does not move.** A record that was already marked and still
  fails keeps the instant it first did.

The writes are core `UPDATE`s: the framework's audit listener stamps
`updated_at`/`updated_by` on any ORM-modified row, and a mark is not an edit —
restamping would reorder the default `-updated_at` listing and name an author
for a change nobody made. `set_committed_value` puts the value back on the
instances the scan holds so the identity map agrees without them going dirty.

Two consequences worth stating. **A forced `apply` never reuses a preview's
report** (`_preview.reused_report`): its scan is what writes the marks, and a
report recorded nothing. And **`rescan` is the one preview that writes**,
which is why the deferred job body lives in `services/preview_runner.py` and
commits — the same argument `reindex_runner` makes.

Duplicates are deliberately outside the column: a record sharing a
newly-unique value fails no per-record rule, and `_duplicates` yields counts
and a sample rather than ids. It is surfaced the way it always was, by
`conflicts_for` topping up `invalid` on the single-record read.

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
   you need DB-assigned values. Exactly three callers commit, and each says
   why in its docstring: `cli_io` (no request exists) and the two deferred-job
   runners, `services/reindex_runner` and `services/preview_runner`, which
   have no `get_db` to commit for them.

Because the error route turns an exception into a *response* inside the handler,
`get_db` never sees it and would commit whatever the refused call already wrote.
Every error path therefore rolls the session back explicitly and clears the
has-writes flag — which is what makes `on_error=abort` and a refused cascading
delete mean *nothing was written*.

### Bulk, and the one thing it adds

`services/bulk.py` does not re-implement anything: each record it names goes
through the same `services.records` call the single-record endpoint makes, so
`allowed_roles`, the `on_delete` cascade, the claims, the revisions and the
index writes cannot drift from the one-record path. What it adds is the
confirmation semantics — a pass that continues past a refusal so the report
can name every one of them, and then refuses the batch entirely.

Two mechanisms carry that. Each record's turn runs inside `db.begin_nested()`
(the shape `services/import_` uses per row), because a refused write leaves
the session needing a rollback and rolling the outer transaction back at the
first refusal would end the pass with one failure named out of five. And
`BulkRefused` — raised, not returned — is what takes the outer transaction
with it through the error route's rollback, which is what makes "nothing was
changed" true rather than aspirational.

**On SQLite a third one is needed to make the second true**, and it is why the
batch takes `lock_type` before the loop. pysqlite emits `BEGIN` only before
the first DML statement it recognises, so a batch whose first statement was
`SAVEPOINT` had that savepoint start the transaction and its `RELEASE` commit
it — the outer rollback then undid nothing. `lock_type` is an `UPDATE` on
SQLite (a `SELECT … FOR UPDATE` on Postgres), so the savepoints nest inside a
transaction that exists. It is also the right thing on its own terms: every
single-record write takes that lock inside `_prepare`, and trash, restore and
purge never reach it. `tests/test_bulk_sqlite_transaction.py` pins the
behaviour on a SQLite database of its own, whatever backend the suite was
pointed at.

It reports back through `bulk.Change`, deliberately event-shaped without being
an event: the service cannot publish (rule 1), so it hands the endpoint the
record, the cascade and the previous status, and the endpoint picks the
`events` builder from the action it asked for.

`services/_empty_trash.py` is the opposite shape and re-exported from the same
module: it names no records, so it is one statement per table over an id set —
`purge_type_records`'s shape narrowed to the trash and to a filter, identities
read first because a `RecordPurged` is the one event nobody can reconstruct
afterwards.

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
| `RecordCreated` | `POST /records`, `POST …/translations`, each import row that created | `type_key`, `tenant_id`, `uuid`, `locale`, `translation_group`, `status` |
| `RecordUpdated` | `PUT /records/{uuid}`, a revision restore, each import row that updated | `type_key`, `tenant_id`, `uuid`, `version`, `status_before`, `status_after` |
| `RecordTrashed` | `DELETE /records/{uuid}` — one per record the delete reached | `type_key`, `tenant_id`, `uuid`, `cascaded_from` |
| `RecordRestored` | `POST …/restore` | `type_key`, `tenant_id`, `uuid` |
| `RecordPurged` | `DELETE …/purge`, and one per record of a deleted type | `type_key`, `tenant_id`, `uuid`, `locale`, `translation_group` |
| `RecordTypeChanged` | `PUT /types/{key}`, a schema rollback, a `mode=update` type import | `type_key`, `tenant_id`, `schema_version`, `kind`, `index_affecting_keys` |
| `RecordTypeDeleted` | `DELETE /types/{key}` | `type_key`, `tenant_id`, `purged` |

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
back. The drain runs after the request's tenant binding has been reset, so
`defer()` captures the bound tenant when a job is queued and binds it again
around the job. A handler therefore runs in the event's `tenant_id`. Bulk
paths emit per record: an import publishes one event per row that wrote (a dry
run publishes none), a cascade one per record trashed, a type delete one
`RecordPurged` per record and then the `RecordTypeDeleted`. A host
with no subscribers pays an `EventBus.publish` that returns before gathering
anything.

A type delete's `RecordPurged` events carry **identity only** — `uuid`,
`locale`, `translation_group` — and never the record's payload. The purge
itself is set-based (one `DELETE` per index table, one for the revisions and
one for the documents, all by `type_id`), so there is no row instantiated to
read a payload from; reading ten thousand of them back to fill events would
reinstate exactly the per-record cost that made deleting a 10,000-record type
take 101 s inside one request. A subscriber that needs a record's content must
have it before the type is deleted.

`RecordTypeChanged` is what makes `register_reduce_provider`'s "run the CLI
afterwards" caveat automatable: `index_affecting_keys` names the fields whose
stored shape just moved, so a provider knows its projection is stale without
diffing anything itself.

## Media library detection

A `media` field is edited with a picker over the host's media library — the
framework's `file_storage` module on a stock host — and **records neither
imports nor proxies it**. A published module must not depend on another plugin
(the same rule `deps.py` follows for `permissions`), and the picker does not
need one: the browser calls the library's JSON API itself, with the session
cookie, under that module's own permissions. Records only has to tell the
browser *where* the API is.

`sm_records/media.py` decides that once, from `on_startup`:

1. `media_api_prefix` (a `BootSettings` field, so `requires_restart`) is read
   as hydrated. `""` means no picker; a path is used as given (a warning if
   nothing matching is mounted there, since it may be a proxy); `null` means
   detect.
2. **Detection is by route shape.** Every endpoint on the app is walked
   through `fastapi.routing.iter_route_contexts` — FastAPI 0.14x includes
   routers lazily, so `app.routes` holds one opaque `_IncludedRouter` per
   module and none of its routes (the sibling modules' tests read the OpenAPI
   schema for the same reason, which is not an option here: building the
   schema at startup caches it before later hooks mount theirs). A prefix
   qualifies when `POST {p}/upload`, `GET {p}/files`, `GET {p}/files/{x}` and
   `GET {p}/files/{x}/download` are all mounted under it. The host's module
   registry (`app.state.sm.modules`) is consulted only to break a tie: a
   module whose `meta.name` is `FileStorage` wins. Two unexplained matches mean
   *off* and a warning, not a guess.
3. Two facts are read off what was found: whether the list route declares a
   `q`/`search` query parameter (file_storage's does not — the picker then
   filters the loaded page and says so), and whether the host's public-route
   registry exempts `GET {p}/files/{id}/download` from `AuthMiddleware`.
4. The result, a frozen `MediaApi`, is parked on the services container
   (`app.state.sm_records.media_api`).

From there:

- `endpoints/views.py` hands the record editor (new and edit) and the record
  list a `media_api` prop — `{prefix, list_path, upload_path,
  file_url_template, meta_url_template, search_param}`, or `null`.
- `pages/RecordEditor.tsx` and `pages/RecordList.tsx` put it in a React
  context (`components/media/MediaApiContext.tsx`), so `fields/MediaField.tsx`
  and `media/MediaCell.tsx` read it without threading a prop through the
  shared `FieldComponentProps`. With `null`, `MediaField` is the old
  id-or-URL text box.
- `utils/media-api.ts` is the browser client: list, metadata, upload (XHR, for
  progress), and one metadata cache shared by the list and the editor for one
  page visit — every Inertia navigation empties it, and a thumbnail that fails
  to load drops its file, so a file deleted in the library reads as "File
  missing" without a reload. It
  reuses `api-net.ts` for the connection failures — a 401 redirects to sign-in
  and a dropped connection is the same `ApiError` it is everywhere — and
  unwraps `file_storage`'s `{detail: {code, message}}` refusals.
- The anonymous read API's list response carries `media_url_template`: the
  download template when step 3 found the download exempt, `null` otherwise.
  The Records list page block renders a `media` value only through it, so on a
  stock host (no exemption, and a download that also requires
  `file_storage.download`) it renders nothing.

**The stored value never changes shape.** `_check_media` still accepts any
string up to 500 characters; the picker stores the file id `file_storage`
returns and derives every URL from it at render time. A legacy `https://`
value renders as a link; an id the library answers `404`/`422` for is shown as
**File missing** and kept.

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
├── media.py         finds the media library the media picker calls, from on_startup
├── constants.py     every route, permission and limit as a named constant
├── settings.py      RecordsSettings (DB-backed) on settings_boot.py's
│                    restart-marked BootSettings, + settings_checks.py
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
├── endpoints/       api/* (JSON), views*.py (Inertia) + _list_view.py (the list screen's offset/keyset query)
├── seed/            the demo dataset
├── pages/*.tsx      auto-discovered Inertia pages — nothing else goes here
├── components/      everything extracted out of a page (+ hooks/, utils/)
└── locales/en.json  every user-visible string
```

**Never add a file under `pages/` that is not a real Inertia page**: the page
name is derived from that path by `import.meta.glob`, so a stray `.tsx`
silently registers a page. Extractions go to `components/`, `hooks/`, `utils/`.
