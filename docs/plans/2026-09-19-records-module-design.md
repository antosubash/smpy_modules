# `records` — a generic structured-content module

**Date:** 2026-09-19
**Status:** design (proposed — not yet implemented)
**Repo:** `smpy_modules` (a distributable add-on, published as `simple_module_records`)

## 1. The name

| | |
|---|---|
| Module name (`ModuleMeta.name`) | `Records` |
| Entry point / module key | `records` |
| Python import package | `sm_records` |
| PyPI distribution | `simple_module_records` |
| npm workspace | `@simple-module-py/records` |
| Table prefix | `records_` |
| Route prefix / view prefix | `/api/records` / `/admin/records` |

Two nouns, and they are load-bearing for every screen and endpoint below:

- a **Record Type** is the schema — "Product", "FAQ Entry", "Team Member";
- a **Record** is one instance of it.

### Why not the obvious names

- **`collections`** — the Directus word, and the clearest one, but the import
  package would shadow the Python standard library's `collections`. Even
  namespaced as `sm_collections` it leaves "collection" describing the
  container while the item still needs its own word.
- **`entities`** — the word in the original request, but it's used for both
  the type and the instance ("create an entity" / "the Product entity"), so
  every API path and screen title stays ambiguous.
- **`content`** — already taken conceptually. `pagebuilder` owns
  `/pagebuilder/content` and its settings talk about `content_locales`.
- **`records`** as a bare import package — `records` is an existing PyPI
  package (Reitz's SQL wrapper). Prefixing follows the precedent already set
  in this repo by the `ai` module, which imports as `sm_ai` for exactly this
  reason.

"Record Type" / "Record" is unambiguous in both directions, survives being
said out loud in a meeting, and leaves `entity` free as informal shorthand.

## 2. Goal

Let an administrator define arbitrary structured content types from the admin
UI and perform full CRUD on their instances, without a developer writing a
module, a SQLModel table, or an Alembic migration for each one.

### In scope (v1)

- Record Types: create / edit / delete, each carrying an ordered list of typed
  field definitions.
- Records: list (paginated, filterable, sortable), create, read, update,
  soft-delete, restore, hard-delete.
- A schema-driven admin UI — one generic list screen and one generic form
  screen serving every type.
- A JSON API mirroring both, for scripting and for other modules.
- Draft/published status per record, with an opt-in public read API per type.
- Validation of every write against the type's current schema.
- Schema evolution that is safe on a type that already holds records.

### Explicit non-goals (v1)

- **Runtime DDL.** No table is created per Record Type. See §3.
- **A query language.** Filtering is a fixed, small grammar (`eq`, `ne`, `in`,
  `contains`, `gt`, `lt`, `is_null`) over declared fields. No arbitrary
  expressions, no user-supplied SQL or JSONPath.
- **Per-record ACLs.** Access is per type, by role. §8.
- **Workflow.** Draft → published is a two-state flag, not pagebuilder's
  submit/approve/reject machine. If a type needs editorial workflow it wants
  pagebuilder, not this.
- **Content i18n.** v1 records are monolingual. Deliberate — see §10.
- **Rich text / visual composition.** A `longtext` field is plain text or
  Markdown. Composed layouts are pagebuilder's job and duplicating that here
  would give the repo two block editors.

## 3. The central decision: one table, not a table per type

This is the decision everything else follows from, so it is worth being blunt
about the alternative before accepting it.

### The rejected option: a real table per Record Type

Strapi and Directus both do this — "add a content type" issues `CREATE TABLE`.
It buys real column types, real indexes, real unique constraints and fast
queries with no JSON extraction.

It is the wrong shape *for this repo specifically*, and not by a small margin:

- `CLAUDE.md` states the invariant plainly: **migrations live in
  `host/migrations/versions/`, never in a module**, and each consuming host
  autogenerates its own revisions from the module's static SQLModel tables.
  Runtime DDL produces tables no model describes, so the next
  `alembic revision --autogenerate` in a host proposes to **drop every one of
  them**. Avoiding that means teaching `make_include_object()` to ignore a
  name pattern, and then the framework's own `SM010`/`SM011` drift checks
  stop being able to tell a missing migration from a dynamic table.
- DDL from an HTTP request races across workers, and neither Postgres nor
  SQLite gives a clean story for a concurrent `ALTER TABLE` under load.
- SQLite is the local-dev default here. Its `ALTER TABLE` support is narrow
  enough that any column change becomes a table rebuild, and the module would
  need two divergent evolution paths for the two supported backends.

### The chosen option: one `records_record` table, payload in a `JSON` column

Every record of every type is a row in one table, with its field values in a
`JSON` column. `pagebuilder` already stores whole page trees this way
(`Page.draft_data`, `Page.published_data` — `sqlalchemy.JSON`, which maps to
`json` on SQLite and `jsonb` on Postgres), so the pattern is proven in this
codebase, on both backends, under the existing migration story.

**Where this hurts, stated up front rather than discovered later.** Filtering
and sorting on a custom field means extracting it from JSON at query time.
That is unindexed, so it degrades linearly. It is fine into the low tens of
thousands of records per type and it is not fine at a million. The mitigation
is designed but deliberately *not built* in v1 — see §5.3 — because building
an EAV index sidecar before anyone has hit the wall is speculative complexity
that has to be maintained on every write forever.

**What is not left to JSON.** The columns that every listing screen actually
sorts and filters by are real columns on the row, not payload keys: `status`,
`slug`, `display_title`, `position`, `published_at`, and the audit columns.
Putting these in JSON would mean the default list view — the single most
frequent query in the module — was the slow path.

## 4. Tables

Three, all under the module's own `Base` (`create_module_base("records")`),
all prefixed `records_`.

### `records_type`

| column | notes |
|---|---|
| `id` | int PK |
| `key` | `str(64)`, **unique**, `^[a-z][a-z0-9_]*$`. The stable identifier used in URLs and the API. Immutable after creation. |
| `label`, `label_plural` | display names |
| `description` | optional |
| `icon` | lucide icon name, for the type list |
| `fields` | `JSON` — ordered list of field definitions, §5 |
| `schema_version` | int, bumped on every change to `fields` |
| `display_field` | which field key supplies `Record.display_title` |
| `slug_field` | optional; which field seeds `Record.slug` |
| `is_public` | bool, default `False` — gates the anonymous read API |
| `allowed_roles` | `JSON` list of role names permitted to write, §8 |
| `record_count` | denormalised, maintained on write |
| + `AuditMixin` | |

`key` is immutable because it appears in URLs, in the public API, and in
`relation` field targets. A rename would strand all three, and the redirect
machinery to fix that is a larger feature than the rename is worth. Renaming
the *label* is free and is what people actually want.

### `records_record`

| column | notes |
|---|---|
| `id` | int PK |
| `uuid` | `str(32)`, unique — the identifier used in relations and the public API, so an export/import round trip doesn't depend on autoincrement |
| `type_id` | int, FK to `records_type`, indexed |
| `data` | `JSON`, non-null, default `{}` — the field values |
| `schema_version` | int — which version of the type's schema this row was written against |
| `status` | enum `draft` / `published`, indexed |
| `slug` | `str(200)`, nullable |
| `display_title` | `str(300)` — denormalised from `display_field` on write, so the list screen never parses JSON to render a row |
| `position` | int, for hand-ordered types |
| `published_at` | tz-aware datetime, nullable, indexed |
| + `AuditMixin`, `SoftDeleteMixin` | |

Indexes: `(type_id, status, position)` for the ordered list, and a partial
unique on `(type_id, slug)` where `slug is not null` for types that use one.

`SoftDeleteMixin` is used and `MultiTenantMixin` is not. Deleting content
should be recoverable; the framework's query filters exclude soft-deleted
rows by default, and the trash view bypasses with
`stmt.execution_options(include_deleted=True)`. Tenancy is left off because
`MultiTenantMixin.tenant_id` is non-nullable at the DB level, so adopting it
forces multi-tenancy on every host that installs the module. Neither
`pagebuilder` nor `news` uses it, and this module has no more reason to.

### `records_revision`

`(id, record_id, schema_version, data JSON, display_title, event, created_at,
created_by)` — an append-only snapshot written on every update and on delete.

Included in v1, not deferred, because it is the cheapest possible insurance
against the failure mode this module is most exposed to: a schema edit or a
bad bulk write silently mangling content, discovered a week later. Retention
is capped per record (`revision_limit`, §9); unbounded revisions on a
frequently-edited type will outgrow the content table itself.

## 5. Field definitions and validation

### 5.1 A closed field-type set, not arbitrary JSON Schema

A field definition is a small object:

```json
{
  "key": "price",
  "type": "number",
  "label": "Price",
  "required": true,
  "unique": false,
  "indexed": false,
  "default": null,
  "help": "Excluding tax",
  "constraints": { "min": 0 },
  "options": null
}
```

with `type` drawn from a closed set: `text`, `longtext`, `number`, `integer`,
`boolean`, `date`, `datetime`, `select`, `multiselect`, `email`, `url`,
`json`, `media`, `relation`.

**Accepting raw JSON Schema from the user was considered and rejected.** It
looks like a free win and is three problems: `$ref` makes it a remote-fetch
and cycle-resolution surface that has to be defended against; a generic form
renderer cannot render an arbitrary schema, so the UI would silently
degrade to a JSON textarea for anything non-trivial; and arbitrary schemas
cannot be diffed, which makes §6 impossible. A closed set is renderable,
diffable, and validatable, and the escape hatch for genuinely unstructured
data is the `json` field type.

### 5.2 Validation by a generated Pydantic model

Each `(type_id, schema_version)` compiles to a Pydantic model via
`pydantic.create_model`, cached in a process-local dict.

Chosen over adding a `jsonschema` dependency because it adds **no new
dependency**, gives coercion and per-field error paths for free, and keeps
the repo's "SQLModel/Pydantic everywhere" convention intact.

Two things the implementation must get right or this backfires:

- **Cache key includes `schema_version`,** and the version is bumped on every
  `fields` write. A cache keyed on `type_id` alone serves the old validator
  after a schema edit — writes then pass validation against a schema that no
  longer exists.
- **Multi-worker invalidation.** The cache is per process. A schema edited in
  worker A is stale in worker B until its next request. Fixed by reading the
  type row (and thus its `schema_version`) inside the request that validates,
  and treating the cache as keyed on the version that row reports — never on
  a version cached alongside it.

### 5.3 Filtering, and the index sidecar that is *not* in v1

v1 filters via SQLAlchemy's dialect-neutral JSON path access
(`Record.data[key].as_string()`), which compiles to `json_extract` on SQLite
and `->>` on Postgres. Unindexed, honest about it, documented in the README
with the rough ceiling.

The planned v2, with its trigger condition written down now so the decision
isn't re-litigated from scratch: a `records_record_index` sidecar
`(record_id, type_id, field_key, text_value, num_value, bool_value,
date_value)`, populated on write for fields marked `indexed: true`, with
composite indexes per value column. **Build it when a real installation has a
type over ~50k records that needs to filter or sort by a custom field, or
needs a DB-enforced `unique` on one.** Not before — it doubles the write path
and adds a join per filter term, permanently, for a problem no one has yet.

Until then, `unique: true` on a field is enforced by the service with a
`SELECT` before write. That is a check-then-act race under concurrency, and
the README must say so rather than implying a guarantee the schema doesn't
make.

## 6. Schema evolution — the part that decides whether this is usable

Everything above is straightforward. This section is where a generic content
store either works or becomes the thing people route around. The rule: a
schema change on a type holding 10,000 records must never be able to silently
corrupt or orphan them.

Every proposed change to `fields` is **diffed against the current version and
classified** before anything is written:

**Additive** — a new optional field, a new `select` option, a relaxed
constraint, a label or help-text edit. Applied immediately. Existing records
are untouched; their payloads simply lack the key, and the read path fills it
from `default`.

**Restrictive** — a new required field, a narrowed type (`text` → `number`),
a tightened constraint, a removed `select` option, a newly `unique` field.
Applied only after a **dry-run validation pass** over the existing records of
that type. The response reports how many rows would fail and gives a sample.
The API refuses the change unless the caller supplies either a `default` that
makes every row valid, or `force: true`, which applies the change and marks
the failing rows `invalid` rather than mutating them.

**Destructive** — deleting a field. The field is removed from `fields` and
the key is *retained in each record's payload* under a reserved `_orphaned`
object. Costs storage; buys back the ability to undo a mis-click that
otherwise destroys a column of content irreversibly. `_orphaned` is purged by
an explicit, separately-permissioned action.

Two invariants that make this hold together:

- **The read path is lenient, the write path is strict.** A record stamped at
  `schema_version` 3 read under version 5 renders with missing keys defaulted
  and unknown keys ignored. Writing it back validates against 5 and restamps.
  A record is therefore migrated lazily, on edit, and never in a bulk job that
  can half-fail.
- **A record that cannot satisfy the current schema is marked, not hidden.**
  `status` gains no third value; instead the list screen surfaces an "invalid
  under current schema" badge derived at read time. A row that disappears from
  the UI because someone tightened a constraint is the failure mode that makes
  people stop trusting the module.

Deleting a Record Type that holds records requires either an empty type or an
explicit `confirm_record_count` matching the actual count — the same shape of
guard the field deletion uses, for the same reason.

## 7. Relations

A `relation` field stores `{"type": "<type_key>", "uuid": "<record uuid>"}`
(or a list of those for a to-many). Validated on write: the target type must
exist and the target record must exist and not be soft-deleted.

- **No automatic expansion.** A list of 50 records each expanding a relation
  is 50 extra queries, and a type related to itself expands forever. Reads
  expand only under an explicit `?expand=field_a,field_b`, one batched query
  per named field, depth 1. Depth > 1 is not supported in v1 and should not be
  added without a cycle guard.
- **Delete behaviour is a property of the field** — `restrict` (default),
  `set_null`, or `cascade` — enforced in the service layer, because there is
  no foreign key to enforce it at the DB. `restrict` is the default because a
  cascade default across a user-defined graph deletes content nobody asked to
  delete.
- Soft-deleting a target leaves referrers pointing at a hidden row. Reads
  resolve it to `null` with a `dangling: true` marker rather than erroring —
  a restorable delete must not break the pages that reference it.

## 8. Permissions, and an honest limitation

`register_permissions` runs at app construction, before the database is open.
Record Types are created at runtime. **Per-type permissions therefore cannot
be registered as framework permissions** — there is no point in the boot
sequence at which the list of types is both known and still registrable.

v1 accepts the consequence rather than working around it:

- Three static permissions: `records.view`, `records.edit`,
  `records.manage_types`. These appear in the role editor and behave normally.
- Per-type narrowing via `RecordType.allowed_roles`, enforced in `deps.py` on
  top of the static permission. Empty means "any role with the static
  permission".

The limitation to write in the README, not bury: **per-type roles are not
visible in the framework's role editor.** An admin editing roles there sees
only the three coarse permissions and will not discover that Products is
restricted to `editor`. The per-type UI lives on the type's own settings
screen, which is discoverable but is a second place to look.

The alternative — a permission string per type registered at boot from a
pre-app DB read — was considered. `_preapp_config` proves an early read is
possible, but it would make type creation require a restart before its
permission became grantable, which is worse.

### Public read API

Off by default. A type with `is_public = True` exposes
`GET /api/records/public/{type_key}` and
`GET /api/records/public/{type_key}/{uuid}`, published records only, with
`draft` rows and the audit columns stripped from the response shape rather
than filtered in the query.

Registered through `register_public_routes` with methods pinned to
`{"GET", "HEAD"}` — and, because the set of public types is only known after
settings hydration, filled from `on_startup` rather than the construction-time
hook, exactly as `pagebuilder.boot.exempt_public_routes` does and for the same
reason. The `startswith` prefix trap applies: the rule terminates in `/`, and
the fixed `/api/records/public/` prefix keeps it from ever matching the admin
surface.

## 9. Settings

DB-backed via `register_module_settings`, no environment variables — the rule
`pagebuilder` and `news` already follow.

| setting | default | restart? |
|---|---|---|
| `public_route_prefix` | `/api/records/public` | yes (`_RESTART`) |
| `default_page_size` | 25 | no |
| `max_page_size` | 200 | no |
| `revision_limit` | 50 per record | no |
| `max_payload_bytes` | 256 KB | no |
| `max_fields_per_type` | 100 | no |

`max_payload_bytes` and `max_fields_per_type` are not ceremony. A `json`
field type accepts arbitrary nested documents; without a cap, one POST can
write a multi-megabyte row that every subsequent list query has to load and
every revision duplicates.

## 10. Frontend

Four pages under `sm_records/pages/`, and nothing else in that directory —
`import.meta.glob` derives page names from the path, so a helper dropped there
silently registers a page. Field renderers, the filter bar and the schema
editor go in `components/`.

| page | route |
|---|---|
| `Types.tsx` | `/admin/records` — the type list |
| `TypeEditor.tsx` | `/admin/records/types/{key}` — the schema editor |
| `RecordList.tsx` | `/admin/records/{key}` — generic, schema-driven list |
| `RecordEditor.tsx` | `/admin/records/{key}/{uuid}` — generic, schema-driven form |

A `components/fields/` directory holds one small component per field type
behind a registry map, mirroring `pagebuilder/components/blockRegistry.ts`.
The 300-line cap makes this the only workable shape anyway — a single
switch-based renderer for fourteen field types does not fit.

**Writes go through `fetch()` against `/api/records/*`, never Inertia's
`router.post()`.** `SM018` fires on exactly that combination, because Inertia
rejects a non-Inertia JSON response. Navigation and flash-message redirects
use Inertia; data mutations use `fetch` and update local state.

**This module ships `locales/en.json` and uses `t(keys.records.…)` from day
one.** That diverges slightly from `CLAUDE.md`'s note that the three existing
modules should convert together — but that note is about not doing piecemeal
conversions during unrelated work, and it is not a reason to add a fourth
module's worth of hardcoded English to the backlog. Retrofitting i18n costs
several times what authoring it does. Zod schemas carrying translated
messages are constructed inside `useT()`, never at module scope, or they
freeze against the first render's locale.

**Why content i18n is out of v1.** `pagebuilder` shows what it actually costs:
locale on every row, uniqueness per `(locale, slug)`, a `translation_group`,
locale-scoped redirects, and the hard rule that a page's language is fixed for
its lifetime. Doing that for user-defined types means every one of those
decisions again, generically. It is a v2 feature and the schema above leaves
room for it — adding `locale` and `translation_group` to `records_record` is
an additive migration. What must *not* happen is a half-version where records
have a locale but slugs aren't scoped to it; that is precisely how `/de/p/x`
starts serving the English page.

## 11. Module wiring

```python
class RecordsModule(ModuleBase):
    meta = ModuleMeta(
        name="Records",
        route_prefix="/api/records",
        view_prefix="/admin/records",
        depends_on=["Settings"],
        version=importlib.metadata.version("simple_module_records"),
        requires_framework=">=1.0,<2.0",
    )
```

Hooks overridden: `register_settings`, `register_permissions`,
`register_menu_items` (section `ADMIN_SIDEBAR`, group `Content`),
`register_routes`, `on_startup` (public-route exemptions + settings-dependent
wiring).

`view_prefix` points at `/admin/records` directly rather than using
`admin_view_prefix` — every screen this module serves is administrative, so it
needs one router, not two. Per the framework docs, the `/admin` prefix is a
URL convention and not a guard; the routes carry their permission dependencies
regardless.

Menu items are registered without `roles`, matching `pagebuilder`'s
reasoning: role filtering is a plain intersection with no admin bypass, so
listing roles there hides the entry from an `admin` user.

## 12. Checklist against `docs/adding-a-module.md`

All ten steps apply. The four that are most often missed here:

- `host/pyproject.toml` — dependency **and** `[tool.uv.sources...] workspace = true`.
- Framework deps as **ranges** (`simple_module_core>=0.0.25,<0.1`), never `==`.
  `version = "0.0.7"` to match `scripts/bump_version.py --check-current`.
- `modules/records/tests` added to `testpaths` in the root `pyproject.toml`;
  a pytest step in `.github/workflows/ci.yml`; and
  `simple_module_records` added to the `publish-pypi` matrix in
  `release.yml` — the last is what actually publishes it.
- The first Alembic revision carries `branch_labels = ("records",)`.

## 13. Tests

Beyond per-endpoint CRUD coverage, the cases that would actually catch a
regression in the decisions above:

- Every field type: valid value, invalid value, missing-and-required,
  missing-and-optional-with-default.
- Schema diff classification — one test per additive / restrictive /
  destructive case, asserting the classification, not just the outcome.
- A restrictive change against a type holding records that would fail it:
  refused without `force`, and with `force` marks rather than mutates.
- A record stamped at an old `schema_version` reads leniently and restamps on
  write.
- Validator cache: edit a schema, then write — the write validates against the
  *new* version.
- `restrict` blocks deleting a referenced record; `set_null` and `cascade` do
  what they say; soft-deleting a target yields `dangling: true`, not a 500.
- `register_public_routes`: asserted against the registry directly, as
  `modules/pagebuilder/tests/test_public_routes.py` does. Playwright specs run
  authenticated and will not catch a missing exemption — and here the
  consequence of one is anonymous read access to unpublished content.
- A private type is not readable via the public endpoint even by uuid.
- `max_payload_bytes` and `max_fields_per_type` are enforced.

## 14. Phasing

**Phase 1 — the spine.** Tables, migration, field-type set, Pydantic
compilation, type CRUD, record CRUD (no relations, no public API), the admin
type list and a JSON-textarea record editor. Ugly but end-to-end, and it
proves the storage decision before any UI is built on it.

**Phase 2 — the UI.** Schema editor, `components/fields/` registry, generic
list with filter/sort/pagination, generic form, `locales/en.json`.

**Phase 3 — safety.** Schema diffing and classification, dry-run validation,
revisions and restore, trash and restore.

**Phase 4 — reach.** Relations with `?expand=`, the public read API,
`is_public` and `allowed_roles`, the README and module docs.

Deferred with conditions attached: the index sidecar (§5.3), content i18n
(§10), CSV/JSON import-export, and a `records` widget for pagebuilder — the
last being the natural integration, and the reason `news` already has
`integrations/pagebuilder.py` to copy the seam from.

## 15. Open questions

1. **Does `slug` belong here at all?** It only matters for types whose records
   are addressable, and nothing in v1 addresses a record by slug — the public
   API uses `uuid`. It may be premature. Cheap to add later; dead weight if
   nobody uses it.
2. **`display_title` denormalisation.** It makes the list screen fast and
   creates a second source of truth that goes stale if the `display_field`
   changes. Recomputing every record on a `display_field` edit is a bulk job
   with exactly the half-failure property §6 tries to avoid. Leaning toward
   recomputing lazily on read-if-stale, but it needs a decision.
3. **Whether revisions should be in Phase 1 rather than Phase 3.** The risk
   they insure against — a bad schema edit — is live from the moment schema
   editing ships in Phase 2.
4. **`media` field type** presumes `file_storage` from the framework repo.
   That adds a dependency for one field type. Alternative: a plain `url` field
   in v1 and `media` when the dependency is justified by more than this.

