# Records — multi-tenancy

*Addendum to [2026-09-19-records-module-design.md](2026-09-19-records-module-design.md)
(§5, which left `MultiTenantMixin` off) and
[2026-09-20-records-phase5-design.md](2026-09-20-records-phase5-design.md).
Design only; nothing here is implemented. Every framework claim is backed by a
spike run on Postgres — the `FACT` ids below point at captured output, see
[Evidence](#evidence).*

## 0. The decision, and what this document decides

The owner has decided that `records` adopts the framework's `MultiTenantMixin`
(`simple_module_db/mixins.py:63`: `tenant_id VARCHAR(50) NOT NULL`, indexed) and
that tenancy becomes a property of every records row. §5 of the original design
refused this because the column is non-nullable and "adopting it forces
multi-tenancy on every host that installs the module". That objection is still
true of the mixin; this document is about making it survivable.

**Recommendation in one paragraph.** Put the mixin on the six *owned* tables
(type, type revision, and each table set's record and revision tables), not
on the derived index/reduce tables. Tie a record's tenant to its type's with a
composite foreign key, so every existing `type_id`-led index and unique
constraint is per-tenant by construction and needs no rebuild. Replace the
proposed "default-tenant fallback" (A.2) with a **mode-aware binding** (A.3):
on a host with no `TenantMiddleware`, records pins every one of its entry points
to the tenant `default`. On a host that has it, records **fails closed** — an
admin request whose user has no tenant is a 403 and an anonymous read with no
tenant is a 404. It never falls back to `default`. A records-owned session
guard turns "records queried with no tenant bound" into an exception, because
the framework's own answer to that case is "return every tenant's rows"
(FACT 1b).

| | |
|---|---|
| Framework | 0.0.26 (`simple_module_{core,db,hosting,test}`, `users`, `auth`), read from `.venv/.../site-packages` |
| Spike DB | Postgres `feat_pg` (schemas `tenancy_spike*`, dropped after), scratch DB `tenancy_spike_app` for the full-app run (dropped after); SQLite file for batch mode |
| Scope | `modules/records` only; framework gaps go upstream (§L) |

---

## 1. What the framework actually does (spike findings)

The coordinator's brief listed framework facts to verify. The table gives each
one's observed answer. **Bold** marks the answers that contradict a reasonable
assumption.

| # | Question | Observed (0.0.26, Postgres) | FACT |
|---|---|---|---|
| 1a | Insert a mixin row with no tenant set | **The listener does nothing** (`listeners.py:122` only stamps when a tenant is set). The DB refuses: `IntegrityError / NotNullViolationError`. Over HTTP that is an unhandled 500. | 1a, 2 |
| 1a′ | No tenant set, explicit `tenant_id="Z"` | Accepted. The mismatch check needs a context tenant. | 1a′ |
| 1a″ | Tenant A set, explicit `tenant_id="B"` | `TenantIsolationError`. | 1a″ |
| 1a‴ | Change `tenant_id` on a loaded row | With a tenant set: `TenantIsolationError`. **With none set: the row silently moves to B** (`listeners.py:152` skips the check). | 1a‴, 1a⁗ |
| 1b | Reads with no tenant set | **Every tenant's rows.** `select(RecordType).where(key==k).first()` (records' `get_type` shape) silently returns an arbitrary tenant's type. | 1b |
| 1c | Which selects get the filter | Filtered: `select(Model)`, `select(Model.id)`, `select(func.count(Model.id))`, with `include_deleted=True` too. **Not filtered:** `select(func.count()).select_from(Model)`, anything over `Model.__table__`, `text()`. | 1c |
| 1d | Subqueries / EXISTS / joins | The criteria are attached only to mappers in the *top-level columns* (`listeners.py:262`, `all_mappers`). **Not filtered:** `exists().where(Model…)`, `x.in_(select(Model.col))`, `select(exists(select(Model.id)))`, `sa.exists()` over mapper or `__table__`, and **a mixin mapper that appears only as a join target**. Filtered: the inner query of `aliased(Model, subq)` when the alias is at top level (records' bounded count, `index/query.py:267`). | 1d |
| 1e | `session.get`, lazy loads, DML, bulk insert | `get()` on a fresh session: filtered. **`get()` of an object already in the identity map returns it without SQL, unfiltered.** Lazy load: filtered. **`update()`/`delete()`: not filtered** (`listeners.py:253`: `is_select` only). **`session.execute(insert(Model), [dicts])` and `insert().values()` bypass `before_flush`: nothing is stamped (IntegrityError).** `add_all()` + flush is stamped. | 1e |
| 1f | Contextvar propagation | Reaches the `AsyncSession.run_sync` greenlet and `create_task` children. **A bare `set()` in awaited code leaks into the caller's task** (under `httpx.ASGITransport` that caller is the test), so every `set` must be paired with a `reset`. | 1e, 1f |
| 2 | Single-tenant host (`multi_tenant=False`) with a mixin table | Boots with no diagnostic or warning. No `TenantMiddleware` is installed. The first write is an unhandled `IntegrityError` → 500. | 2 |
| 2′ | Middleware order (outermost first) | `… Session → MenuSync → BodyLimit → DeferredJobs → Csrf → Auth → Tenant → Locale → Inertia`. **Every records middleware runs outside `AuthMiddleware` and `TenantMiddleware`** (`_phase_helpers.py:99-102` adds Tenant before the module middleware; `add_middleware` is LIFO). | 2, 3 |
| 2″ | Deferred jobs | **`sm_records.deferred.defer()` jobs run with no tenant**: handler saw `'A'`, job saw `None`, because `TenantMiddleware` reset the var before `DeferredJobsMiddleware` drains. | 3 |
| 2‴ | A yield dependency that binds a tenant | Works. Router-level dependencies are entered before `get_db` and exited after it, so an `add()` with no flush is stamped at `get_db`'s commit. The var is reset afterwards and nothing leaks into the test task. | 2 |
| 3 | `authenticated_client` / `create_admin` user | `users_user.tenant_id` is nullable (`users/models/user.py:59`). `create_admin` takes no tenant, so the admin has `None`. | 3 |
| 3′ | Tenant-less *authenticated* user + header | **The header chooses any tenant** (`middleware.py:191`: the header is consulted whenever the user's tenant is `None`). | 3 |
| 3″ | Moving a user between tenants | **Invisible until re-login.** `UserContext` (including `tenant_id`) is cached in the session cookie (`users/provider.py:40-43`). | 3 |
| 3‴ | Anonymous request | With the header: that tenant. Without it: `None`, and a write is an `IntegrityError` → 500. | 3 |
| 4 | Tenant management | None. `UserCreate`/`UserUpdate` (`users/contracts/schemas.py:35,44`) have no `tenant_id`, and there is no UI or API. Nothing outside users/auth/settings/feature-flags reads a tenant. | grep |
| 5 | Anonymous tenant source | Only the configured header (`tenant_header`). | 3 |
| 0.0.26 | Where `multi_tenant` is read | `install_middleware` reads the `Settings` passed to `create_app` (env: `SM_MULTI_TENANT`). The DB-hydrated `HostSettings.multi_tenant` arrives at lifespan and changes nothing. Records must therefore detect *the installed middleware*, not the setting. | code |

Migration / plan facts (spike 3, the real `sm_records` schema, 200k records):

| Question | Observed | FACT |
|---|---|---|
| `ADD COLUMN tenant_id VARCHAR(50) NOT NULL DEFAULT 'default'` on 200k rows | 1.1 ms. The table is not rewritten (filenode unchanged, `atthasmissing=true`). | D-pg |
| Dropping the default afterwards | ~1 ms per table (catalog only). A raw insert without `tenant_id` is an `IntegrityError` again. | D-pg |
| `(tenant_id, uuid)` unique on 200k rows / composite FK swap | 463–524 ms / 57–58 ms (two runs) | D-pg |
| Composite FK `(type_id, tenant_id) → records_type(id, tenant_id)` | A record in `acme` naming a `default` type → `IntegrityError` (Postgres, and SQLite with `PRAGMA foreign_keys=ON`). | D-pg, D-sqlite |
| SQLite `batch_alter_table(recreate="always")` | **Silently recreates the three `…_desc` indexes ascending** (`DESC` lost). The partial slug unique survives. Re-issuing the three from the model after the batch restores them verbatim. | D-sqlite (both runs) |
| Per-tenant listing on the existing `(type_id, col, id)` indexes | `Index Scan using ix_records_record_type_updated_desc … Index Cond: (type_id = 48) Filter: (is_deleted IS FALSE AND tenant_id = 'acme')` → 25 rows read for 25 returned. Keyset, slug and count use the existing indexes the same way. | E-plan |
| uuid lookup | `Index Scan using uq_records_record_tenant_uuid` | E-plan |

---

## A. Single-tenant hosts — the binding

### A.0 What has to be true

1. Every records statement runs with `current_tenant_id` bound (1b: unbound
   reads cross tenants silently; 1a: unbound writes are 500s; 1a‴: unbound
   updates can move rows).
2. The bound tenant is the *right* one for the caller, and a caller that has
   none is refused rather than guessed.
3. The binding covers every path in §A.4, not just requests.

### A.1 Option 1 — hard-require `multi_tenant=True`

Records would fail boot unless `TenantMiddleware` is installed. That is honest
but hostile. Every single-tenant install (the default, and this repo's
`.env.example`, which sets `SM_MULTI_TENANT=false`) stops booting on upgrade.
The operator's fix, turning multi-tenancy on, still leaves them with users
whose `tenant_id` is `None` (3) and no UI to set it (4). **Rejected.**

### A.2 Option 2 — records-owned default fallback (the coordinator's leaning)

*"When no tenant is set, sm_records sets `current_tenant_id` to a configured
default via its own middleware/dependency."*

**Safe with respect to the flush listener? Yes, mechanically.** With a tenant
always bound, the listener stamps every new row (1e `add_all`), refuses
explicit mismatches (1a″) and refuses tenant changes (1a‴). It is safer than
today's unbound state, where those checks are off. The listener is not the
problem.

**Unsafe as a policy, for three reasons:**

1. **It fails open on a multi-tenant host.** After the migration, every
   existing row is in `default`. On a multi-tenant host the requests with no
   tenant are exactly these (3, 3‴): the bootstrap admin, every user created
   through the users UI (neither API can set `tenant_id`), and every anonymous
   caller without the header. A2 hands all of them the legacy tenant's data,
   read and write. That is the one tenant that holds real data. A missing
   tenant should be refused, not silently mapped onto a real tenant.
2. **It is in the wrong place if it is middleware.** Records middleware runs
   outside Auth and Tenant (2′). It cannot see the resolved tenant, so it can
   only pre-set `default` and hope `TenantMiddleware` overrides it. It would
   then pin the *global* contextvar for every other module's requests as well.
   Worse, `DeferredJobsMiddleware` drains after Tenant's reset (2″). A
   fallback set outside it would run a tenant-A request's deferred reindex and
   event publication **as `default`**. `reindex_runner.run_pending` would load
   A's type by id under the `default` filter, find nothing, and return 0: a
   pending reindex that silently never runs.
3. **It does not cover the non-request paths at all** (CLI, health, startup,
   deferred jobs). Those need the same binding by other means, which is most
   of the work anyway.

### A.3 Recommendation — mode-aware binding at records' own entry points, fail closed

**Mode** is decided once, in `RecordsModule.on_startup`, by inspecting the
built stack: `TenantMiddleware in {m.cls for m in app.user_middleware}`. The
setting is not used: in 0.0.26 a DB edit of `multi_tenant` does not rebuild
the stack (§1). The mode is stored on the services container as
`app.state.sm_records.tenancy`. If the stack and `app.state.host.settings.multi_tenant`
disagree, records logs a warning.

| Mode | Admin API + views | Public API | Deferred / CLI / background |
|---|---|---|---|
| **single** (no `TenantMiddleware`) | bind `DEFAULT_TENANT = "default"`; ignore any user `tenant_id` or header | bind `default` | bind `default`, or the tenant of the row being worked on |
| **multi** | bind `request.state.user.tenant_id`; **if `None` → 403 `tenant_required`**, even if a header supplied one (3′) | bind the framework-resolved tenant (header, or a logged-in user's); **if `None` → 404** (same body as an unknown type, so it is no oracle) | the tenant captured from the request, or the row's own `tenant_id` |

`DEFAULT_TENANT` is a **constant**, not a setting. The migration backfills that
literal (§D), so a setting that could drift from it would strand the legacy
data. Single mode is exactly A.2's behaviour, but confined to the hosts where
it is correct. Multi mode never falls back.

*Optional, later (Phase 7):* a records setting
`admin_header_tenant: bool = False`. It would let a user holding `admin` with
no tenant of their own act in the tenant their header names, for operators who
administer several tenants. It is off by default because it reproduces
fact 3′, deliberately.

### A.4 New module `sm_records/tenancy.py`

```python
DEFAULT_TENANT: Final = "default"
ALL_TENANTS: Final = "records_all_tenants"        # execution option: an explicit cross-tenant read
TENANT_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,49}$")

class TenancyMode(StrEnum): SINGLE = "single"; MULTI = "multi"
class TenantRequired(Forbidden): code = "tenant_required"      # 403 in services/errors.py
class TenantUnbound(RuntimeError): ...                          # a bug, never a user error

def detect_mode(app) -> TenancyMode                    # middleware-stack inspection
@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[str]      # validate, set, ALWAYS reset (1f);
                                                       # refuse re-binding to a *different* tenant
def bound_tenant() -> str                              # current_tenant_id.get() or raise TenantUnbound
def resolve_admin(request) -> str                      # table above; raises TenantRequired
def resolve_public(request) -> str | None              # None -> caller answers 404
async def bind_admin(request) -> AsyncIterator[str]    # yield dependency, wraps tenant_scope
async def bind_public(request) -> AsyncIterator[str]   # yield dependency, 404 on None
def all_tenants(stmt)                                  # stmt.execution_options(**{ALL_TENANTS: True})
def install_guard(sync_session_class) -> None          # below; idempotent
```

**Router wiring.** Add `Depends(bind_admin)` to `APIRouter(dependencies=…)` in
`endpoints/api/__init__.py` and to the view router (`endpoints/views.py:48`,
which includes `views_types`). Add `Depends(bind_public)` to
`endpoints/api/public.py:71`. **Order is load-bearing: the binding must be
first in the list.** Yield dependencies exit in reverse order of entry, and
`require_view` (`permissions.deps`) opens `get_db`. If it were entered first,
the tenant would be reset *before* `get_db`'s exit commits, and any object
still pending at commit would flush unbound. FastAPI prepends a parent
router's dependencies to every included route's, so "first on the router"
means first for every route. Spike 2‴ shows the correct order stamps an
unflushed `add()` at commit. Phase 3 adds a test that pins it.

**The guard** (`install_guard`, spike 1g) registers two listeners on the
host's `sync_session_class`: once from `on_startup` (`app.state.sm.db`), and
once from every CLI `init_db` site.

* `do_orm_execute`: if a tenant-owned records mapper is among
  `all_mappers`, no tenant is bound, and the statement is not tagged
  `ALL_TENANTS` → `TenantUnbound`.
* `before_flush`: any new or dirty tenant-owned records object with no tenant
  bound → `TenantUnbound`. This closes 1a‴'s silent move and replaces 1a's
  500-with-a-NOT-NULL-message with an error that names the bug.

The guard sees mappers only. Core statements over `__table__` are not caught
(1g), which is what the explicit-predicate rule in §E is for.

### A.5 Every path that touches records tables outside a tenant-bearing request

Found by reading `module.py`, `deferred.py`, `_menu_middleware.py`, `menu.py`,
`health.py`, `boot.py`, `cli*.py`, `seed/`, `services/*_runner.py`,
`services/preview_jobs.py` and `events.py`:

| Path | Today | Required |
|---|---|---|
| `deferred.defer()` → `DeferredJobsMiddleware` (reindex after a type write `endpoints/api/types.py:64`; schema preview `endpoints/api/preview.py:135`; event publication `events.py:82`) | runs unbound (2″) | `defer()` captures `bound_tenant()` and wraps the job: `async with`/`with tenant_scope(t): await job()`. The detached fallback path (`deferred.py:74`) gets the same wrapper. |
| `events._publish_all` → subscribers | unbound; events carry `type_key` + `uuid` only, and those are ambiguous across tenants | publish inside the captured scope; **add `tenant_id: str` to every event in `contracts/events.py`**. This is a published contract, so it needs a changelog entry. |
| `services/reindex_runner.run_pending(db_state, type_id)` | opens its own session, reads the type by id | read the type with `all_tenants(...)`, then run the rest inside `tenant_scope(rtype.tenant_id)` |
| `services/preview_runner` + `services/preview_jobs` (process-global `_jobs`) | job keyed by uuid and checked by `type_key` (`preview.py:174`) | store `tenant_id` + `type_id` on `PreviewJob`. The lookup compares `found.type_id != rtype.id` (type ids are global). The runner binds the job's tenant. |
| `MenuSyncMiddleware` → `menu.refresh` → `load_menu_types` | outside Tenant, reads every tenant's `show_in_menu` types | single: `tenant_scope(DEFAULT_TENANT)`; multi: no per-type items (§I) |
| `on_startup`: `health.count_orphaned_locales` | unbound read | `all_tenants`, counted per `(tenant_id, locale)` |
| `on_startup`: `menu.refresh(force=True)` | unbound | same as MenuSync |
| `health.stale_reindex_check` (`/health/ready`) | unbound read of every type | `all_tenants`; the detail names `tenant/key`. Read-only by construction. |
| `health.count_invalid_records` (`_invalid.py:194`) | unbound | `all_tenants` |
| CLI `reindex [--type K]`, `verify`, `export`, `import`, `seed [--reset]`, `_force_pending` | own `init_db` + `register_listeners`, unbound | `--tenant T` on every subcommand, defaulting to `DEFAULT_TENANT` and validated with `TENANT_RE`. `reindex`/`verify` without `--type` enumerate pending types across tenants (`all_tenants`) and run each in `tenant_scope(rtype.tenant_id)`. `install_guard` on the CLI's `db_state`. New read-only `records tenants` lists tenants present in `records_type`/`records_record` with counts. |
| `seed.runner._reset` | deletes types by key | inside `tenant_scope(--tenant)`; it can only see and delete that tenant's types |
| `boot.mount_public_router` / `exempt_public_routes` / `media.configure` | no DB | none |
| Index-provider and reduce-provider registries (process-global, keyed by type **key**) | — | no change, but documented: a provider registered for `article` applies to every tenant's `article`. |

---

## B. Which tables get the mixin

**Rule.** A table gets `MultiTenantMixin` when the unit of work writes its
rows and the ORM reads them as a top-level entity. That is where the mixin
does anything: stamping (1e `add_all`) and filtering (1c). A table whose rows
are *derived* stays without it: it is written by bulk DML (1e: never
stamped) and read only as a join target or inside EXISTS/IN (1d: never
filtered). Its tenant comes through the join to its record, as
`docs/architecture.md` §"Index rows carry no record state" already says of
"any future tenant filter".

| Table (global set; each collection `records_c_<name>_*` identical) | Mixin | Why |
|---|---|---|
| `records_type` | **yes** | tenant root; looked up by natural key |
| `records_type_revision` | **yes** | ORM-added (`services/_schema.py:168`), read top-level (`revisions.py:65`, `_rollback.py:49`) |
| `<set>_record` | **yes** | tenant root; looked up by uuid/slug |
| `<set>_revision` | **yes** | ORM-added (`services/revisions.py:91`), read top-level (`revisions.py:44,127,210`) |
| `<set>_index_{text,number,bool,date,datetime,ref}` | no | derived. Written by `add_all` (`index/writer.py:268`) and by bulk `insert(table)` (`index/reindex.py:108`). Read as `IN`/join/subquery (`index/_filters.py:121`, `_sorting.py:121`). Scoped by `type_id`/`record_id`. The mixin would add an unused btree to the hottest write path, and a NOT NULL trap to the bulk path, while protecting none of these reads (1d). |
| `records_index_reduce` | no | a fold keyed by `type_id`. Written by `insert().values()`/`update()` (`index/_reduce_write.py:80,110`), neither stamped nor filtered. |

**The one alternative worth naming.** Mixin on all 22 tables in the global set
plus collections. It costs a 50-byte column and a btree on every index row, and
it would require rewriting every bulk insert to pass `tenant_id` explicitly. It
buys a filter that would not apply to how those tables are queried (1d).
Rejected. If the owner wants the literal reading of "every table", this is the
cost.

**The invariant that makes the rule sound: a composite FK.**
`records_type` gains `UNIQUE (id, tenant_id)`, and every set's record table's
`type_id` FK becomes `(type_id, tenant_id) → records_type (id, tenant_id) ON
DELETE RESTRICT`. The FK keeps its current name
`fk_<table>_type_id_records_type` (the naming convention keys on
`column_0`). The revision takes the name from the model's
`ForeignKeyConstraint` rather than spelling it, because a long collection name
pushes it past 63 bytes, where SQLAlchemy hash-truncates it (the warning in
`models/_index.py`'s docstring). A record can then never belong to a different tenant from its
type (FACT D-pg). Every `type_id`-scoped statement, index row, unique
constraint and reduce row is per-tenant by construction. Revisions reach their
tenant through `record_id`. The services also set `tenant_id=rtype.tenant_id`
explicitly on create (§F), so a mismatch is a `TenantIsolationError` before it
is an FK error.

**How factory tables get the column.** In `models/_record.py`,
`_Record(AuditMixin, SoftDeleteMixin)` becomes `_Record(AuditMixin,
SoftDeleteMixin, MultiTenantMixin)` and `_Revision(SQLModel)` becomes
`_Revision(MultiTenantMixin)`. The mixin uses `sa_column_kwargs`, not
`sa_column`, so each generated class gets its own `Column` (the comment at
`mixins.py:1-7`). `type_id`'s `sa_column=Column(ForeignKey(...))` loses its
`ForeignKey` and the composite `ForeignKeyConstraint` goes into
`record_args()` (`models/_record_args.py`). `RecordType` and
`RecordTypeRevision` inherit the mixin directly. The `_RECORD_DOC` paragraph
explaining why the mixin is absent is replaced. `tests/test_collections_ddl.py`
keeps proving the collection DDL equals the global DDL modulo prefix.

**Indexes.** The brief expected "`tenant_id` must lead the keyset/sort/lookup
indexes or the per-tenant listing loses its index". **Measured, that is not
true here.** Every list, keyset, slug, count and filter statement is narrowed by
`type_id`, and `type_id` determines the tenant (composite FK). The existing
`(type_id, col, id)` indexes serve the per-tenant page with `tenant_id` as a
residual filter that removes zero rows (FACT E-plan: 25 read / 25 returned). The
count already needs the heap for `is_deleted`. Adding `tenant_id` in front of
18 indexes per set would double the index DDL churn of this migration and
widen every entry, and no measured query needs it. **No existing index
changes.** New indexes are:

* `ix_<t>_tenant_id` on each of the six mixin tables (the mixin's own
  `index=True`). It serves `records tenants`, the orphan scan and whole-tenant
  deletes. Not on the derived tables.
* `uq_records_type_tenant_key (tenant_id, key)` and `uq_<set>_record_tenant_uuid
  (tenant_id, uuid)`, which replace global uniques (§C) and serve the two
  natural-key lookups. EXPLAIN shows `type by key` as a seq scan over 80 types;
  that is the planner's correct choice at that size and not a finding.

---

## C. Uniqueness

Every UNIQUE in the module (from `pg_indexes`/`pg_constraint` on feat_pg):

| Constraint | Today | New definition | Why |
|---|---|---|---|
| `ix_records_type_key` | `UNIQUE (key)` | **dropped**. New: `uq_records_type_tenant_key UNIQUE (tenant_id, key)` | two tenants may both have `post` (FACT C) |
| `ix_<set>_record_uuid` | `UNIQUE (uuid)` | **dropped**. New: `uq_<set>_record_tenant_uuid UNIQUE (tenant_id, uuid)` | Export from A and import into B must be able to keep uuids (tenant cloning). A global unique would also make B's import 409 on A's uuid, which is an existence oracle across tenants. |
| `ix_<set>_record_type_slug` | `UNIQUE (type_id, locale, slug) WHERE slug IS NOT NULL` | **unchanged** | `type_id` implies the tenant (composite FK) |
| `ix_<set>_record_group_locale` | `UNIQUE (type_id, translation_group, locale)` | **unchanged** | same |
| `uq_records_index_reduce_group` | `UNIQUE (type_id, key, group_value)` | **unchanged** | same |
| new | — | `uq_records_type_id_tenant_id UNIQUE (id, tenant_id)` | target of the composite FK |
| `unique` *fields* (application-level, `index/query.exists_query`) | per type | unchanged | same |

Leaving the partial slug index alone also avoids the hazard
`_record_args.py` documents: autogenerate cannot see a `WHERE` change, so
rebuilding it by hand is a risk with no benefit.

**Signatures.** `RecordTables.slug_signatures`/`group_locale_signatures`
(`models/_record.py`) are unchanged. The new `(tenant_id, uuid)` collision on
import is recognised the same way: add `uuid_signatures =
(f"uq_{t}_tenant_uuid", f"{t}.tenant_id, {t}.uuid")` and map it to the existing
409.

**Cross-collection uuid uniqueness** (`models/_record.py:new_uuid` docstring,
`services/_uuids.py:uuids_claimed_elsewhere`) is now "unique per tenant across
collections". Those checks are ORM selects on the record mapper, so they are
tenant-filtered (1c) and need no code change, only the docstring.

---

## D. Migration

One hand-written revision, `host/migrations/versions/<rev>_records_tenant_id.py`,
`down_revision = "8f3d223f8605"` (current head). It iterates `table_sets()`
filtered by `_present_sets()` exactly as `fe3ea2dfe0fb` does, so a collection
created later gets the columns from its own autogenerated creation revision.

**Backfill.** Add the column with `server_default='default'`. On Postgres ≥ 11
that is a catalog-only fast default: 1.1 ms on 200k rows, no table rewrite
(FACT D-pg). **Drop the default in the same revision.** If the default stays, a
forgotten tenant (a bulk insert, a script, a future code path) lands silently
in `default` instead of failing. That is the failure the mixin's docstring
promises cannot happen, and FACT D-pg shows the drop restores it. It also keeps
the migrated schema equal to a `create_all` one (the model declares no
default), avoiding the `show_in_menu` drift `_type.py` describes.

```python
DEFAULT = "default"          # == sm_records.tenancy.DEFAULT_TENANT, repeated here on purpose:
                             # a revision must not change meaning if the constant ever moves

def _owned(sets):            # records_type, records_type_revision, <set>_record, <set>_revision
    ...

def upgrade() -> None:
    sets = _present_sets()
    pg = op.get_bind().dialect.name == "postgresql"
    for t in _owned(sets):
        op.add_column(t, sa.Column("tenant_id", sa.String(50), nullable=False,
                                   server_default=DEFAULT))
        op.create_index(f"ix_{t}_tenant_id", t, ["tenant_id"])
    op.drop_index("ix_records_type_key", table_name="records_type")
    op.create_index("uq_records_type_tenant_key", "records_type", ["tenant_id", "key"], unique=True)
    for ts in sets:
        rec = ts.record.__tablename__
        op.drop_index(f"ix_{rec}_uuid", table_name=rec)
        op.create_index(f"uq_{rec}_tenant_uuid", rec, ["tenant_id", "uuid"], unique=True)
    if pg:
        op.create_unique_constraint("uq_records_type_id_tenant_id", "records_type", ["id", "tenant_id"])
        for ts in sets:
            rec, fk = ts.record.__tablename__, f"fk_{ts.record.__tablename__}_type_id_records_type"
            op.drop_constraint(fk, rec, type_="foreignkey")
            op.create_foreign_key(fk, rec, "records_type", ["type_id", "tenant_id"],
                                  ["id", "tenant_id"], ondelete="RESTRICT")
        for t in _owned(sets):
            op.alter_column(t, "tenant_id", server_default=None,
                            existing_type=sa.String(50), existing_nullable=False)
    else:  # SQLite: constraint changes and DROP DEFAULT need a table rebuild
        for t in _owned(sets):
            with op.batch_alter_table(t, recreate="always") as b:
                b.alter_column("tenant_id", server_default=None,
                               existing_type=sa.String(50), existing_nullable=False)
                if t == "records_type":
                    b.create_unique_constraint("uq_records_type_id_tenant_id", ["id", "tenant_id"])
                if t in {ts.record.__tablename__ for ts in sets}:
                    fk = f"fk_{t}_type_id_records_type"
                    b.drop_constraint(fk, type_="foreignkey")
                    b.create_foreign_key(fk, "records_type", ["type_id", "tenant_id"],
                                         ["id", "tenant_id"], ondelete="RESTRICT")
        # batch recreate reflects the DESC indexes as ASC (FACT D-sqlite): re-issue them
        bind = op.get_bind()
        for ts in sets:
            table = ts.record.__table__
            for name in descending_index_names(table.name):
                op.drop_index(name, table_name=table.name)
                next(i for i in table.indexes if i.name == name).create(bind)
```

These are the ops `tenancy/spike/test_spike_migration.py::upgrade` ran on both
backends. The final revision is that function with `_present_sets()` and the
`as_sql` branch from `fe3ea2dfe0fb`.

* **Offline `--sql`:** the SQLite branch cannot run offline (batch reflects).
  That matches every earlier records revision's SQLite story. The Postgres
  branch is plain DDL.
* **Lock profile (Postgres):** `ADD COLUMN` with a constant default and `DROP
  DEFAULT` take `ACCESS EXCLUSIVE` briefly with no rewrite. `CREATE UNIQUE
  INDEX` on `(tenant_id, uuid)` blocks writes for its duration (~0.5 s / 200k
  rows). A host with millions of records should run it as `CREATE INDEX
  CONCURRENTLY` in a separate, non-transactional revision; say so in
  `docs/operations.md`. Adding the FK validates every row (~60 ms / 200k). Use
  `NOT VALID` + `VALIDATE CONSTRAINT` for large tables.
* **Downgrade:** drop the FK and recreate the single-column one, drop
  `uq_records_type_id_tenant_id`, drop the `(tenant_id, …)` uniques and recreate
  `ix_records_type_key`/`ix_<set>_record_uuid` unique, then drop the column.
  **Lossy and refusable.** It fails if two tenants share a type key or a uuid,
  and it merges tenants' data. The docstring says so, as `fe3ea2dfe0fb` does.
* **Test DBs:** `tests/pg_support.py` builds with `create_all(checkfirst=True)`,
  which never alters, so existing Postgres test databases (`feat_pg`,
  `records_unit`, …) must be dropped and recreated once. Its docstring
  already says this.

---

## E. Read paths

**Rule (agreeing with the brief, with one refinement).** A statement over a
tenant-owned table must do one of two things:

1. **(a)** Name that table's mapper in its top-level columns and run under a
   bound tenant. The framework filter applies (1c), and the guard (§A.4) makes
   "bound" an invariant rather than a hope.
2. **(b)** Carry an explicit `<table>.tenant_id == bound_tenant()` predicate.

(b) is **mandatory**, never optional, for: Core `__table__` selects, `text()`,
`update()`/`delete()`, `select(func.count()).select_from(X)`, and a
tenant-owned table appearing only in a join target, `exists()` or `in_()`
subquery (1c, 1d, 1e). It is also required, belt-and-braces, in the
**natural-key lookups** that turn a user-supplied string into a row: type by
key, record by uuid, record by slug, public lookups. Those are where a wrong
tenant would be an enumeration oracle. The loader criteria are then a safety
net everywhere else, not the thing isolation rests on. I don't recommend
adding (b) to all ~60 `select(Mapper)` sites. It is churn with no added
protection once the guard exists, and it hides the sites that genuinely need
it among ones that do not.

Audit of every `select(` in `services/`, `index/`, `health.py`, `menu.py`,
`cli*.py`, `seed/` (78 sites) and every DML statement:

| Site | Shape | Covered by | Action |
|---|---|---|---|
| `services/types.py:88` `get_type`, `:95` `get_type_by_id`, `:152` key-taken check; `services/public.py:157` | `select(RecordType).where(key==…).first()` | (a) | **(b) add `RecordType.tenant_id == bound_tenant()`** (natural key; 1b shows `.first()` picks arbitrarily when unbound) |
| `services/records.py:93` record by uuid; `_claims.py:105` slug claim; `public.py:183` public record/list; `_translations.py:58,111,135,159`; `_import_match.py:140,164` | `select(cls)…` | (a) | (b) on the uuid/slug lookups (`records.py:93`, `_claims.py:105`, `public.py:183`, `_import_match.py:140,164`); the rest (a) |
| `index/query.py:115,142,183,295` list/filter/count/exists | `select(record…)` + `in_(select(index.record_id))` | (a) for record; index subquery is **not** filtered (1d) but is `type_id`-scoped → tenant by FK | none |
| `index/query.py:261-268` bounded count | `aliased(record, inner.subquery())` | (a) — inner filtered (FACT 1d, `count over aliased…` = 1) | none; pin with a test |
| `index/_sorting.py:121`, `index/_filters.py:121` | index-table subqueries | `type_id` scope | none |
| `index/aggregate.py:203` | `select(func.count(distinct(record.id)), …).select_from(record)` | (a) (record in columns) | none |
| `services/_referrer_page.py:88-141` referrer panel counts/page | **Core `__table__` join + `func.count()` over a subquery** | **nothing** (1c, 1d) | **(b) mandatory: `rows.c.tenant_id == tenant` in `pair_rows`** |
| `services/_referrers.py:110` ref rows by `(target_uuid, target_type_id)`; `:143` `_by_id` | index mapper (no mixin) / record mapper | `target_type_id` is tenant-bound; `_by_id` is (a) | none |
| `services/_referrer_sets.py:91`, `_referrer_page.py:157`, `_common.py:76`, `expand.py:154` | `select(RecordType…)` (all types) | (a) | none |
| `expand.py:186`, `_relations.py:116`, `_uuids.py:96,127` | record by uuid set | (a) (`include_deleted` keeps the tenant filter, 1e) | none (G relies on these; tested) |
| `services/_duplicates.py:111` | `select(index.value, func.count()).join(record)`; record is a **join target** → not filtered (1d) | `type_id` scope | none; `:134` is (a) |
| `services/_invalid.py:175` | `count(record.id)` per type | (a) | none |
| `services/_invalid.py:194` / `health.count_invalid_records` | `count(cls.id)` over *all* types | (a) in a request; unbound in health | tag `all_tenants` in health |
| `services/_empty_trash.py:103`, `_lifecycle.py:240`, `_orphaned.py:57`, `_dry_run.py:60`, `_titles.py:52`, `_type_update.py:112`, `_common.py:158,186`, `revisions.py:44,65,78,127,210`, `_rollback.py:49` | `select(Mapper)` | (a) | none |
| `services/aggregate.py:127,137`, `index/_reduce_write.py:185` | `IndexReduce` by `type_id` | `type_id` scope | none |
| `reindex_runner.py:78,178`, `index/reindex.py:165,225`, `reduce_rebuild.py:89`, `index/_batch.py:71` | types/records by id | (a) once bound | runner binds `rtype.tenant_id` (§A.5) |
| `health.py:146,186`, `menu.py:135`, `cli.py:68,76,126`, `cli_verify.py:42` | unbound today | — | `all_tenants` (health, CLI enumeration) or `tenant_scope` (menu single mode, CLI with `--tenant`) |
| **DML** `_lifecycle.py:182-183,247,257-261` (purge / type purge; `:258` has an `in_(select(cls.id))` subquery), `_empty_trash.py:71-73`, `_invalid.py:108`, `_common.py:138` (versioned update), `_lock.py:60`, `revisions.py:137`, `types.py:239` | `update()`/`delete()` | **nothing** (1e) — keyed by ids from tenant-scoped reads today | **(b) mandatory on every statement whose table has the mixin**. Deletes on index tables stay keyed by `record_id`/`type_id`. |

**Identity map (1e).** `session.get()` returns an already-loaded object
unfiltered. Records sessions are per request and per job, and binding happens
before the session exists (router dependency order, 2‴), so no object is ever
loaded under another tenant within one session. `tenant_scope` refuses to
re-bind to a *different* tenant, so a CLI loop must open a fresh session per
tenant. That rule is documented in `tenancy.py`.

---

## F. Write paths

| Path | Today | Change |
|---|---|---|
| `services/types.create_type`, `_schema` (type revision) | ORM add | stamped from the bound tenant; no code change beyond the guard |
| `services/records.create_record`, `_translations.create_translation`, import creates (`_import_rows.py`), seed | `Record(type_id=rtype.id, …)` | **set `tenant_id=rtype.tenant_id` explicitly**. The listener then refuses a context/type disagreement (1a″) before the composite FK would. |
| `services/revisions.write_revision` | ORM add | stamped |
| `index/writer.py` (`add_all`), `index/reindex.py:108` (bulk `insert`), `index/_reduce_write.py`, `index/reduce_rebuild.py:144` | derived tables | **no change** (no column); 1e's bulk-insert trap does not apply |
| bulk (`services/bulk.py`, `_bulk_turn.py`), restore, rollback, invalid-mark (`_invalid.py:108`), empty-trash, purge | per-record ORM + DML | ORM parts stamped; DML gets (b) per §E |
| import (`services/import_.py`, CLI) | ORM | runs in the request's / `--tenant`'s scope; the uuid collision check (`_uuids.py`) is per tenant (§C); `uuid_signatures` → 409 |
| reindex / preview (deferred, CLI) | unbound | `tenant_scope(rtype.tenant_id)` (§A.5) |
| type delete (`types.py:239-240`) | DML + `db.delete` | (b) on the DML |

---

## G. Cross-tenant references

1. **Relations** are validated in `services/_relations.py:116`: `select(cls.uuid,
   cls.type_id).where(cls.uuid.in_(uuids))` across every set. It is a top-level
   record mapper, so under a bound tenant another tenant's uuid is *not
   found*. The write is refused with "no record with uuid …", which does not
   reveal that the uuid exists elsewhere. The target type is resolved by key
   through `RecordType` (a), so it is the caller's tenant's type. No new code;
   an isolation test pins it.
2. **Ref rows** are written against the declared target `(target_uuid,
   target_type_id)`, and `target_type_id` is the caller's tenant's type. So
   "who references X" (`_referrers.py:110`, `_referrer_page.py`) only matches
   same-tenant rows once (1) holds. `_referrer_page` also gets its mandatory
   explicit predicate (§E).
3. **Record → type** is enforced by the composite FK (§B).
4. **`?expand=`** (`services/expand.py:186`) resolves by uuid with (a).
5. **Media** fields store a `file_storage` file id. `file_storage` is not
   tenant-aware, so a media id from tenant B is accepted in tenant A. Records
   cannot fix this (it does not own the library); it goes upstream (§L7).

---

## H. Cursors, ETags, cache keys

* **Keyset cursor** (`index/_cursor.py:sort_signature`): add `"n":
  bound_tenant()` to the signed spec. A cursor minted in A and replayed in B
  then fails cleanly as a 400 `CursorError`. Before this change it was not a
  leak: the predicate still applies and the values are the caller's own. It
  was just meaningless.
* **Public responses** (`endpoints/api/_public_cache.py`): in multi mode add
  `Vary: <tenant_header>` next to `ETag`/`Cache-Control: public`. Without it a
  CDN keyed by URL serves tenant A's list to tenant B. The ETag is a content
  digest; equal payloads in two tenants sharing an ETag is harmless.
* **Preview jobs** (`services/preview_jobs._jobs`): `tenant_id`/`type_id` on the
  job, and the lookup compares `type_id`, not `type_key` (`preview.py:174`).
* **Validator cache** (`schema/compile`) is keyed by `type_id`, which is
  global. No change.
* **Menu state** (`module._type_menu_items`) is per process (§I).
* **Export**: the JSON envelope `{"type": …, "records": …}`
  (`services/export.py:168`) gains an informational `"tenant"`. The importer
  ignores it and always imports into the bound tenant, which is what makes
  export-from-A / import-into-B tenant cloning. CSV is unchanged.

---

## I. Per-tenant sidebar

`MenuRegistry` is one static list per process (`simple_module_core/menu.py:43`),
and `MenuSyncMiddleware` runs before auth and tenant resolution (2′). A
per-type entry therefore cannot be per-tenant under 0.0.26. With several
tenants, syncing them would show every tenant's type labels to everyone (a
cross-tenant label leak), linking to `/records/types/<key>`, which resolves
under the *viewer's* tenant to a 404 or a different type with the same key.

**Least-bad behaviour:**

* **single mode:** unchanged, with `load_menu_types` inside
  `tenant_scope(DEFAULT_TENANT)`.
* **multi mode:** `refresh()` syncs no per-type items (`sync_type_menu(registry,
  [], …)`); only the "All record types" hub entry remains. The hub page lists
  the viewer's tenant's types, so nothing becomes unreachable. The type editor
  hides the `show_in_menu` toggle in multi mode (a view prop), and the API
  accepts and stores the flag but documents it as inert.

**Ask upstream (#340):** a per-request menu provider. The provider would be
`register_menu_provider(fn: Callable[[Request], Awaitable[list[MenuItem]]])`,
evaluated by `InertiaLayoutDataMiddleware`, which already runs *inside* Tenant
and so sees `request.state.tenant_id`, and merged into the `menus` prop. Records
would then drop `MenuSyncMiddleware` entirely.

---

## J. Tenant management — what an operator does

The framework has no tenant concept beyond a nullable `users_user.tenant_id`
(§1 row 4). To run two tenants:

1. Set `SM_MULTI_TENANT=true` and, if anonymous public reads or API clients
   need to choose a tenant, `SM_TENANT_HEADER=X-Tenant-ID` in the environment.
   In 0.0.26 the DB setting alone does not install the middleware (§1). Restart.
2. Assign every user a tenant: `UPDATE users_user SET tenant_id='acme' WHERE
   email=…`. There is no UI or API for it (`UserCreate`/`UserUpdate` lack the
   field). **Legacy users must get `tenant_id='default'` to keep seeing the
   pre-migration data.** Users must log out and in again (3″).
3. Users with no tenant, the bootstrap admin included, get 403
   `tenant_required` on every records admin screen. That is intended (A.3).
4. Anonymous readers and headless clients send `X-Tenant-ID: acme`. The
   pagebuilder `RecordsList` block gains an optional **Tenant** field
   (`components/widget/RecordsListBlock.tsx`), sent as that header by
   `utils/public-api.fetchPublicRecords`. With no header, public reads are 404
   in multi mode.

Records exposes:

* `--tenant` on every CLI subcommand, and `records tenants`
* `tenant_id` on every domain event
* `tenant` in the JSON export envelope
* `tenant/key` in health details
* the resolved tenant as a read-only `tenant` view prop, so the UI can show
  which tenant the admin is working in

Records never creates or renames tenants. A tenant exists when a user or a
header names it. `tenant_scope` validates the string with `TENANT_RE`; a
header that fails it is treated as no tenant (404), never as a 500.

**Switching modes on a live install.** Single → multi: data stays in
`default`, and step 2 decides who sees it. Multi → single: only `default` is
visible; other tenants' rows are untouched but unreachable. In single mode the
health check reports the per-tenant row counts outside `default`, so this is
never silent.

---

## K. Test plan

All suites run on SQLite by default and on Postgres via
`SM_TEST_DATABASE_URL` (the existing `tests/pg_support.py` switch).

**Harness** (`tests/app_harness.py`): `_HeaderAuthMiddleware` gains
`X-Test-Tenant`, which sets `request.state.user.tenant_id`. `build_app(...,
tenancy="single"|"multi")` installs `TenantMiddleware(header="X-Tenant-ID")`
in multi mode, so the harness has the production stack shape. The records
fixtures (`conftest.create_type/create_record`) run inside
`tenant_scope(DEFAULT_TENANT)`. A new `two_tenants` fixture seeds, in `acme`
and `globex`, the **same** type key, the same slug, the same translation
group and (via import) the same uuid.

1. **Isolation matrix** (`tests/test_tenancy_isolation.py`,
   `tests/test_tenancy_isolation_io.py`, `tests/test_tenancy_isolation_public.py`,
   each under 300 lines). For every endpoint in `endpoints/api/*` and
   `endpoints/views*.py`, a caller in `globex`:
   * cannot read, list, filter, sort, count, aggregate, export, update, delete,
     restore, purge, roll back, bulk-act on, translate, expand into, reference,
     or list referrers of `acme`'s rows;
   * gets exactly the response an unknown key or uuid gets (404, or the same
     422 as a missing uuid for a relation);
   * cannot see `acme`'s referrers or bulk results. Bulk with a mixed list is
     refused per item as "not found".

   Parametrised over the route table (`app.routes`) so a new route without a
   case fails `test_every_route_has_an_isolation_case`.
2. **Public API**: `X-Tenant-ID` selects the tenant; none → 404 in multi mode,
   `default` in single mode. `Vary` is present in multi mode. The widget query
   is scoped the same way.
3. **Cursors / ETags**: a cursor from `acme` replayed in `globex` → 400; ETag
   and `Vary` headers.
4. **Deferred and background**: a type write in `acme` enqueues a reindex that
   runs in `acme` (index rows exist; the marker clears). Events carry
   `tenant_id='acme'`, and a subscriber sees `current_tenant_id == 'acme'`. A
   preview job id from `acme` is 404 under `globex`'s same-key type.
5. **Guard**: an unbound `select(Record)` → `TenantUnbound`; `all_tenants` is
   allowed; an unbound flush of a record → `TenantUnbound`; a tenant change on a
   loaded record → `TenantIsolationError`.
6. **Single-tenant fallback**: no `TenantMiddleware`. Everything works
   unchanged, every row is stamped `default`, and a user's `tenant_id` and an
   `X-Tenant-ID` header are both ignored. `test_collections_inert.py`-style:
   the existing suite passes unmodified in single mode. *This is the
   acceptance test for "single-tenant hosts keep working".*
7. **Multi mode refusal**: an authenticated user with `tenant_id=None` → 403
   `tenant_required` on API and views, even with a header. Anonymous with no
   header → 404.
8. **Per-tenant uniqueness**: the same type key, slug, uuid and translation
   group in two tenants all succeed. The same collision inside one tenant is
   still the existing 409 (API and import, both backends, racing writes, as in
   `test_unique_concurrency.py`).
9. **Composite FK** (Postgres; SQLite with `PRAGMA foreign_keys=ON`): a
   record whose `tenant_id` differs from its type's is refused.
10. **Migration on a populated DB** (`tests/test_migration_tenant_id.py`):
    build the schema at `8f3d223f8605` on both backends (global set plus one
    collection), insert types, records, revisions and index rows, run
    `upgrade`, and assert:
    * every owned row is `default`;
    * no `server_default` remains;
    * the DESC index SQL is identical to before (SQLite);
    * the composite FK and the new uniques exist;
    * the pre-existing slug and group uniques are unchanged.

    Then run `downgrade` on single-tenant data and assert the round trip.
11. **CLI**: `--tenant` scoping for `export`, `import`, `seed --reset`,
    `reindex --type`, and `verify`; `records tenants`.
12. **Statement census (tripwire, not proof)**: a Postgres-job-only fixture
    hooks `before_cursor_execute`. For each statement naming a tenant-owned
    table, it asserts `tenant_id` appears in the SQL, unless the statement's
    execution options carry `ALL_TENANTS`. It runs over the whole suite. It
    catches a new Core/DML/text statement that forgot (b). It cannot see a
    subquery that shares the statement with a filtered top-level table; the
    matrix in (1) covers those.

**Perf** (`tests/perf`): re-run `test_read_path.py`/`test_write_path.py`
statement-count assertions. The binding adds no statement. The explicit
predicates add no statement. The write path gains one btree insert per record
and per revision (`ix_*_tenant_id`), which should be recorded in
`docs/performance.md`.

---

## L. Framework gaps to file upstream (antosubash/simple_module_python)

| # | Gap | Where | Why records cannot fix it | Proposed API |
|---|---|---|---|---|
| L1 | #332 breadth: tenant (and soft-delete) criteria only reach mappers in the top-level columns; not join targets, `exists()`, `in_()`, `count().select_from()`, Core or DML | `simple_module_db/listeners.py:253` (`is_select`), `:262` (`all_mappers`) | the hook is the framework's; records can only avoid the shapes | attach `with_loader_criteria` for every mixin mapper reachable from the statement (walk `froms`/subqueries), or use a `do_orm_execute` that also covers `is_update`/`is_delete`; document the remaining Core hole |
| L2 | Unbound reads return every tenant | `listeners.py:273` (`tenant_id is not None`) | a module can add a guard (records does, §A.4) but every other adopter repeats it | a `strict_tenancy` setting: raise when a mixin mapper is queried with no tenant, with an `all_tenants=True` execution option as the escape hatch |
| L3 | Unbound flush skips the tenant-change check, so a row can silently move | `listeners.py:152` | same as L2 | check `tenant_id` history whenever it changes, bound or not, unless `all_tenants` |
| L4 | Bulk `insert(Model)` is not stamped | `listeners.py` (`before_flush` only) | records avoids it by design | stamp in `do_orm_execute` for `is_insert` ORM statements (add `tenant_id` to params) |
| L5 | Authenticated users with no tenant can pick any tenant by header | `simple_module_hosting/middleware.py:191` | records refuses them (A.3) but other modules do not | only consult the header for anonymous requests, or behind `tenant_header_for_users: bool = False` |
| L6 | No default tenant / nullable variant | `simple_module_db/mixins.py:63-80` | the column is the mixin's | `HostSettings.default_tenant` applied by `TenantMiddleware` (and by a `tenant_scope()` helper shipped by `simple_module_db`), so modules stop inventing their own `default` |
| L7 | No tenant management: `UserCreate`/`UserUpdate` lack `tenant_id`, `create_admin` takes none, no UI; `file_storage` media is not tenant-scoped | `users/contracts/schemas.py:35,44`; `users/bootstrap.py:51` | records does not own users or media | `tenant_id` on the admin user forms and `create_admin(tenant_id=)`; `MultiTenantMixin` on `file_storage` |
| L8 | Tenant changes are invisible until re-login | `users/provider.py:40-43` (`UserContext` cached in the session) | owned by users | invalidate the cached context when `tenant_id` or roles change (a version stamp on the user row) |
| L9 | Anonymous tenant resolution is header-only | `middleware.py:157-204` | a path or host strategy needs routing the framework owns | pluggable resolvers: `TenantMiddleware(resolvers=[user, header, host_map, path_prefix])` |
| L10 | Module middleware runs outside Auth/Tenant, so deferred work and sidebar sync lose the tenant; no framework "after commit" hook | `simple_module_hosting/_phase_helpers.py:99-102` | records captures and re-binds (§A.5) | an `after_commit` job hook run inside the tenant scope, or a module-middleware slot inside Tenant |
| L11 | Per-request menus (#340) | `simple_module_core/menu.py:43` | the registry is static | `register_menu_provider(request → items)` (§I) |
| L12 | `multi_tenant` DB edits do nothing in 0.0.26 | `_phase_helpers.py:99` reads build-time `Settings` | — | already addressed in the framework repo by `merge_host_settings` per its CLAUDE.md; confirm it covers `multi_tenant`/`tenant_header` |
| L13 | Contextvar hygiene | `listeners.py:23` | — | ship `tenant_scope()` (set + reset) in `simple_module_db` and document "never bare `set()`" (1f) |

---

## Implementation plan

Each phase leaves the suite green on both backends and is reviewable alone.

| Phase | Content | Files | Tests | Effort |
|---|---|---|---|---|
| **1. Tenancy primitives** | `tenancy.py` (constants, mode detection, `tenant_scope`, resolvers, bind dependencies, guard); `TenantRequired` in `services/errors.py` + error table row; mode on the services container at `on_startup`. Nothing is wired yet. | `sm_records/tenancy.py`, `services/errors.py`, `endpoints/api/_error_table.py`, `docs/api-reference.md` error table, `module.py` | `test_tenancy_primitives.py`: scope set/reset/refuse re-bind, `TENANT_RE`, mode detection on real stacks, guard (spike 1g ported) | 0.5 d |
| **2. Schema + migration** | Mixin on the 6 owned classes; composite FK in `record_args`; `(tenant_id,key)`/`(tenant_id,uuid)` uniques; `uuid_signatures`; migration revision; harness/fixtures run in `tenant_scope(DEFAULT_TENANT)`. | `models/_type.py`, `models/_record.py`, `models/_record_args.py`, `models/__init__.py`, `services/_claims.py`, `host/migrations/versions/<rev>_records_tenant_id.py`, `tests/conftest.py`, `tests/app_harness.py`, `tests/perf/conftest.py` | `test_migration_tenant_id.py` (K10), `test_collections_ddl.py`/`test_collections_inert.py` updated (the inert list gains the new indexes), K9, K8 at service level | 1.5 d |
| **3. Request binding + explicit predicates** | `bind_admin`/`bind_public` on the three routers (API, views, public); explicit (b) predicates per §E; the natural-key lookups; `tenant_id=rtype.tenant_id` on creates; `install_guard` at startup. Single mode is now complete. | `endpoints/api/__init__.py`, `endpoints/views.py`, `endpoints/api/public.py`, `services/{types,records,public,_claims,_import_match,_referrer_page,_lifecycle,_empty_trash,_invalid,_common,_lock,revisions,_translations,_import_rows}.py`, `seed/runner.py` | K6 (whole suite in single mode), K7, K5 | 2 d |
| **4. Out-of-request paths** | `defer()` capture/re-bind; `tenant_id` on events; reindex/preview runners; preview job `type_id` check; health `all_tenants` + per-tenant detail; `count_orphaned_locales`; CLI `--tenant` + `records tenants`. | `deferred.py`, `events.py`, `contracts/events.py`, `services/{reindex_runner,preview_runner,preview_jobs}.py`, `endpoints/api/preview.py`, `health.py`, `cli.py`, `cli_io.py`, `cli_verify.py` | K4, K11, `test_events*.py` updated | 1.5 d |
| **5. Isolation matrix** | Two-tenant fixture and the per-route matrix; cursor tenant in the signature; `Vary`; export `tenant`. | `tests/test_tenancy_isolation*.py`, `index/_cursor.py`, `endpoints/api/_public_cache.py`, `services/export.py` | K1, K2, K3, K12 | 2 d |
| **6. Sidebar + UI** | Multi-mode menu (hub only); `tenant` view prop; hide `show_in_menu` in multi mode; widget `tenant` field + header; i18n keys. | `menu.py`, `_menu_middleware.py`, `endpoints/views*.py`, `pages/*`, `components/widget/*`, `utils/public-api.ts`, `locales/en.json` | `test_menu*.py` both modes; vitest for the widget header | 1 d |
| **7. Docs + upstream** | README "Multi-tenancy" section, `docs/operations.md` runbook (§J, large-table index/FK advice), `docs/architecture.md`, `performance.md` numbers; file L1–L13; optional `admin_header_tenant` setting. | docs | `test_docs_error_table.py` | 1 d |

Total about 9.5 engineer-days, of which the isolation matrix and the
out-of-request paths carry most of the risk.

---

## Risks

1. **The filter is narrower than it looks.** Isolation rests on the guard
   plus the §E rule. A future contributor writing an `exists()` over the
   record table, or a Core query, gets no protection from the framework (1d).
   The census test (K12) and review are the mitigation. L1 upstream is the
   real fix.
2. **The operator burden is real and silent without records' checks.** No
   tenant UI, the session-cached tenant, and header trust for tenant-less users
   are all framework-side (L5, L7, L8). A.3's fail-closed refusal is what keeps
   them from becoming data leaks. The cost is that a freshly flipped
   multi-tenant host shows 403s until users are assigned.
3. **Published contract changes.** Events gain `tenant_id`, the JSON export gains
   `tenant`, and public reads need a header in multi mode. Subscribers outside
   this repo must be told.
4. **Downgrade is lossy** once two tenants share a key or uuid.
5. **Large-table migration.** The unique index and FK validation lock writes.
   Use the `CONCURRENTLY` / `NOT VALID` path above ~1M records.
6. **SQLite batch** silently degrades DESC indexes unless the revision
   re-issues them (FACT D-sqlite). This is pinned by K10.
7. **Provider registries are keyed by type key.** A host registering an index
   or reduce provider for `article` applies it to every tenant's `article`.
   That is acceptable for code-level providers, but documented.

---

## Evidence

Spike sources and captured output, all under the session scratchpad
`tenancy/spike/`:

* `test_spike_orm_tenancy.py` → `output_orm_and_migration.txt`: FACT 1a–1g. Runs
  in schema `tenancy_spike` of feat_pg, with toy mixin models under the
  framework's own `register_listeners`.
* `test_spike_migration.py` → `output_orm_and_migration.txt` (FACT D-pg, C,
  E-plan, D-sqlite) and `output_sqlite_without_desc_repair.txt` (the batch run
  without the DESC repair). Runs against the real `sm_records` metadata (global
  set + collection `spk`), 200k records, in schema `tenancy_spike_mig`.
* `test_spike_app_tenancy.py` → `output_app.txt`: FACT 2, 3. Uses real
  `create_app` with every installed module, on the scratch database
  `tenancy_spike_app`, run from the repo root because `create_app` resolves
  `host/templates` from the CWD.

---

## Implementation notes — Phases 1 and 2

Where the code, once written, disagreed with the text above. Each item is
marked so a later phase can find it.

* **Deviation: the harness needs no request middleware.** §K's harness binds
  `default` with a sync autouse fixture in `tests/conftest.py`
  (`tenant_scope(DEFAULT_TENANT)`). pytest-asyncio runs every async fixture and
  test in a copy of that context, and `httpx.ASGITransport` runs the app in the
  test's own task, so every request a test makes is bound too. No temporary
  test-only middleware was added. Tests about the unbound state opt out with
  `@pytest.mark.unbound_tenant`. Phase 3's multi-mode tests will need the same
  opt-out, or a scope of their own.
* **Deviation: `tenant_id` is a reserved field key.** `RESERVED_FIELD_KEYS` is
  derived from `Record.__table__.columns`, so the new column joined it, and
  `components/typeeditor/rules.ts` mirrors it. Like `invalid` before it, an
  install whose type already declares a `tenant_id` field has that type answer
  422 after the upgrade. `docs/operations.md` has the pre-upgrade check.
* **Deviation: the 403 carries a `code`.** `TenantRequired` lives in
  `services/errors.py` and is re-exported by `tenancy.py`. Its body is
  `{"detail", "code": "tenant_required"}`, and the OpenAPI 403 model became
  `ForbiddenBody` (`detail` plus an optional `code`). A missing permission still
  sends no `code`.
* **Deviation: the admin resolver on an anonymous request.** In multi mode
  `resolve_admin` raises the framework's 401 (`Not authenticated`) when there
  is no user at all. It raises `tenant_required` only for a signed-in user whose
  `tenant_id` is `None` or fails `TENANT_RE`. In production `AuthMiddleware`
  answers first, so the 401 is reached only by harnesses.
* **Deviation: the guard also refuses unbound deletes.** `before_flush` checks
  `session.deleted`, as well as new and modified objects. It lives in
  `sm_records/_tenant_guard.py`; `tenancy.install_guard` delegates to it.
* **Deviation: `uuid_taken` is in `services/_uuids.py`, not `_claims.py`.**
  `_claims.py` is at the file cap, and the uuid module is where the other uuid
  claims already live. `flush_write` and `_import_rows` both use it.
  `_import_rows` now says "uuid … is already in use" when the uuid key refused,
  and keeps the combined sentence for the translation-group key.
* **Deviation: the revision runs `ANALYZE` on SQLite.** It analyses every owned
  table after the rebuild, for the reason `c4a17b9de0f2` gives. Every records
  statement now filters on `tenant_id`, and an unanalysed `ix_*_tenant_id`
  looks maximally selective to SQLite's planner. The downgrade also repairs
  the `DESC` indexes, because its table rebuild flattens them too.
* **Deviation: `install_guard` is idempotent through a class flag, not
  `event.contains`.** The framework builds a new session class per `init_db`,
  and SQLAlchemy's event registry keys listeners by `id()`. After an old class
  is garbage-collected, a new class can reuse its id while the registry still
  holds the dead entry. `event.contains` then reported the guard as installed
  on a class that had no listener. This showed up as an order-dependent
  Postgres failure. The guard now sets `_sm_records_tenant_guard` in the
  class's own `__dict__`.
* **Correction (§B): the record FK is never hash-truncated.**
  `fk_records_c_<name>_record_type_id_records_type` is 41 + len(name) bytes,
  which is exactly 63 at `MAX_COLLECTION_NAME_LEN` = 22. The revision still
  reads the name off the model's constraint, which is correct either way.
* **Correction (Phase 2 plan row): `test_collections_inert.py` needed no
  change.** It compares table lists, not indexes. `test_collections_ddl.py`
  passes unchanged, because the factory gives every generated class its own
  mixin `Column`.
* **One existing test changed.** `test_export_stream.py`'s fixture bulk-inserts
  through `insert(Record.__table__)`, which is never stamped (FACT 1e), so it
  now passes `tenant_id` itself. No other existing test changed.
* **Not in the plan's file list.** `tests/perf/_schema.py` backfills
  `tenant_id` with `'default'` when it upgrades a reused perf database. The
  perf worker subprocess (`tests/perf/_collection_worker.py`) binds `default`
  itself.
* **K10 runs the real chain.** `tests/test_migration_tenant_id.py` builds the
  schema by running the host's revisions to `8f3d223f8605` in an `alembic`
  subprocess. On Postgres it uses a scratch schema selected with
  `search_path`. It then upgrades, asserts, and also runs `alembic check`,
  which is clean for records on both backends.
* **Between Phase 2 and Phase 3 the real host cannot write records.** Nothing
  binds a tenant outside the test suite yet. The demo host, the e2e suite and
  the CLI (`seed`, `import`, `reindex`) hit `NOT NULL` on `tenant_id` until
  Phases 3 and 4 land. Reads work, and on a single-tenant database they return
  what they did before.
* **Framework gaps found (add to §L):**
  * **L14.** `HostSettings` (`simple_module_hosting/host_settings.py:14`) has no
    `env_prefix`, and `_phase_helpers.py:193` registers it bare. So
    `app.state.host.settings.multi_tenant` stays `False` on a host that set
    `SM_MULTI_TENANT=true`, unless the DB row says otherwise. On such a host,
    records' startup warning about the setting disagreeing with the stack
    fires on every boot.
  * **L15.** `simple_module_db.session.init_db` never turns on SQLite's
    `PRAGMA foreign_keys`. On a SQLite host every foreign key is unenforced,
    including the composite type key. K9 turns it on per session to prove the
    constraint.

---

## Implementation notes — Phase 3

Request binding, the explicit predicates and the create stamp. Items are marked
as in the Phase 1–2 notes.

* **Wired as designed.** `Depends(bind_admin)` is the first dependency of
  `endpoints/api/__init__.py`'s router and of `endpoints/views.py`'s (which
  includes `views_types`); `Depends(bind_public)` is the first of
  `endpoints/api/public.py`'s. FastAPI 0.141 wraps an included router in an
  `_IncludedRouter`, and it still enters a parent router's dependencies before
  an included one's (checked). The response is sent inside FastAPI's request
  exit stack, so the binding is also still live when anything commits at
  `http.response.start`. `tests/test_tenancy_binding.py` pins the order
  with the routers' real dependency lists, using an unflushed `add()` stamped
  at `get_db`'s commit. A control that puts the binding after `require_view`
  is refused by the guard with `TenantUnbound`.
* **Deviation: `admin_header_tenant` landed here, not in Phase 7.** It is a
  DB-backed records setting, default `False`, read per request. In multi mode
  it lets a user whose `tenant_id` is `None` and who holds the `admin` role act
  in `request.state.tenant_id`, the tenant the framework resolved from the
  header. Some cases are still refused with `tenant_required`: a non-admin, a
  missing header, a header failing `TENANT_RE`, and a user whose own tenant is
  set but malformed. A user with a valid tenant of their own always gets that
  tenant, whatever the header says.
* **Deviation: the startup warning fires in one direction only.** It fires
  when `HostSettings.multi_tenant` is on and the stack has no
  `TenantMiddleware`, which is an admin-UI edit that changed nothing. It does
  not fire for a multi stack with the setting off. That is every host
  configured through `SM_MULTI_TENANT`, because of L14.
* **Explicit predicates (§E), as listed**, plus a few sites the table left
  implicit:
  * `get_type_by_id` goes through the same `_owned_types()` as `get_type`.
  * The public list narrows by tenant inside `_published_only`, so the page
    and both halves of the bounded count carry it.
  * `_translations.published_siblings` (a public read) carries it.
  * `_import_match._by_column` carries it before `scoped`. The uuid match
    spans every type in the table set, so the tenant is its only boundary.
  * `purge_type_records` carries it on both `DELETE`s and inside the `IN`
    subquery.
  * `_translations` `_sibling`/`_free_slug`/`list_translations` stay (a),
    as the table says.
* **§F done in one place.** `records.create_record` sets
  `tenant_id=rtype.tenant_id`, and translations, import and seed all create
  through it. `seed/` needed no edit.
* **View props.** `tenancy.view_props(request)` adds a read-only `tenant` and
  a `tenancy_mode` (`"single"`/`"multi"`) to all six records screens.
  **Deviation from K6's "unmodified":** `test_views.py`'s four exact prop-set
  assertions gained the two keys. No other pre-existing test changed except
  `test_tenancy_primitives.py`'s warning test, for the item above.
* **Harness.** `build_app(..., tenancy="single"|"multi")`. Multi installs the
  framework's `TenantMiddleware(header="X-Tenant-ID")` inside auth and inside
  the module's middleware. `X-Test-Tenant` sets the stub user's `tenant_id`.
  Either mode now calls `tenancy.configure` and `install_guard` the way
  `on_startup` does, so every HTTP test runs under the guard. The stub-auth
  half moved to `tests/harness_auth.py` for the file cap and is re-exported
  from `app_harness`.
* **Census helper, not K12.** `tests/tenancy_support.statements` records the
  SQL one service call sends. `unscoped_writes` then lists any
  `UPDATE`/`DELETE` of an owned table whose `WHERE` lacks `tenant_id`. It
  exempts the unit of work's own `WHERE <t>.id = :p` writes, which are
  objects loaded under the tenant and covered by the guard's `before_flush`.
  It is used where the effect cannot be observed: the type lock, the
  hard-delete purge (`_purge` expunges its records, so it cannot be handed
  another tenant's) and the revision prune. The suite-wide Postgres census of
  K12 stays with Phase 5. Every predicate test in `test_tenancy_predicates.py`
  failed with the service changes reverted, and passed with them.
* **Interim state, until Phase 4 is merged.** The guard is installed at the
  top of `on_startup`. That is what the design asks, and it proves Phase 4's
  startup reads are bound. But until Phase 4 lands, the real host **fails to
  boot**: `health.count_orphaned_locales` reads unbound and raises
  `TenantUnbound`. This was verified by booting `host/main.py` on a migrated
  scratch copy of `host/app.db`. With those two reads bound (simulated), the
  host boots and the public API answers. `/health/ready` still reports the
  unbound `stale_reindex_check`, and deferred jobs (reindex, events, preview)
  log `TenantUnbound` until Phase 4 captures the tenant in `defer()`.
* **Framework gap found (add to §L):**
  * **L16.** `TenantMiddleware` (`simple_module_hosting/middleware.py:191-196`)
    binds `current_tenant_id` to the raw header value with no validation, of
    any length or characters. Records treats a value failing `TENANT_RE` as no
    tenant, but other `MultiTenantMixin` adopters filter by it and stamp it.
    On Postgres a header longer than the 50-character column fails the write
    with a 500.
