# `records` — a generic structured-content module

**Date:** 2026-09-19
**Status:** design (proposed — not yet implemented)
**Repo:** `smpy_modules` (a distributable add-on, published as `simple_module_records`)
**Prior art this follows:** [YesSql](https://github.com/sebastienros/yessql) and the
content layer Orchard Core builds on it.

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

Two nouns, load-bearing for every screen and endpoint below:

- a **Record Type** is the schema — "Product", "FAQ Entry", "Team Member";
- a **Record** is one instance of it.

### Why not the obvious names

- **`collections`** — the Directus word, and the clearest one, but the import
  package would shadow the Python standard library's `collections`. It also
  collides with YesSql's own meaning of "collection" (a document partition),
  which this design borrows in §12.
- **`entities`** — the word in the original request, but it names both the
  type and the instance ("create an entity" / "the Product entity"), so every
  API path and screen title stays ambiguous.
- **`content`** — already taken conceptually. `pagebuilder` owns
  `/pagebuilder/content` and its settings talk about `content_locales`.
- **`records`** as a bare import package — `records` is an existing PyPI
  package. Prefixing follows the precedent the `ai` module already set in this
  repo by importing as `sm_ai`.

## 2. Goal

Let an administrator define arbitrary structured content types from the admin
UI and perform full CRUD on their instances, without a developer writing a
module, a SQLModel table, or an Alembic migration for each one.

### In scope (v1)

- Record Types: create / edit / delete, each carrying an ordered list of typed
  field definitions.
- Records: list (paginated, filtered, sorted), create, read, update,
  soft-delete, restore, hard-delete — with optimistic concurrency.
- **An index layer** that makes declared fields genuinely queryable in SQL.
- A schema-driven admin UI — one generic list screen and one generic form
  screen serving every type.
- A JSON API mirroring both.
- Draft/published status per record, with an opt-in public read API per type.
- Validation of every write against the type's current schema.
- Schema evolution that is safe on a type that already holds records.

### Explicit non-goals (v1)

- **Runtime DDL.** No table is created per Record Type. §4.
- **Querying the document payload.** If a field is not indexed, it is not
  queryable. §7.2 — this is a deliberate hard rule, not a limitation.
- **Reduce indexes.** Map indexes only in v1. §7.5.
- **Per-record ACLs.** Access is per type, by role. §10.
- **Workflow.** Draft → published is a two-state flag, not pagebuilder's
  submit/approve/reject machine.
- **Content i18n.** v1 records are monolingual. §12.
- **Rich text / visual composition.** Composed layouts are pagebuilder's job.

## 3. What YesSql is, and what transfers

YesSql is a document database over a relational one. Its shape is four ideas:

1. **One global `Document` table.** Verified against the source, the whole
   schema is four columns:

   | column | type | purpose |
   |---|---|---|
   | `Id` | `long` | identity |
   | `Type` | `string` | which CLR type this document is |
   | `Content` | `string` | the serialized JSON |
   | `Version` | `long` | optimistic concurrency |

2. **Indexes are separate, real, typed tables.** An index is a plain class;
   each gets its own SQL table with real columns and real indexes.

   ```csharp
   public class BlogPostByAuthor : MapIndex
   {
       public string Author { get; set; }
   }
   ```

3. **An `IndexProvider` declares the projection**, and it is the only place
   that knows how a document becomes index rows:

   ```csharp
   public class BlogPostIndexProvider : IndexProvider<BlogPost>
   {
       public override void Describe(DescribeContext<BlogPost> context)
       {
           context.For<BlogPostByAuthor>()
               .Map(blogPost => new BlogPostByAuthor { Author = blogPost.Author });
       }
   }
   ```

4. **Queries run against the index, and return documents.** The payload is
   never searched:

   ```csharp
   var ps = await session
       .Query<BlogPost, BlogPostByAuthor>(x => x.Author.StartsWith("B"))
       .ListAsync();
   ```

   `MapIndex` is 1:1 or 1:N document→index and carries a `DocumentId`.
   `ReduceIndex` is N:1 and adds a **bridge table** so many documents can
   map to one aggregated row. Index tables are created in migrations via
   `ISchemaBuilder.CreateMapIndexTableAsync` /
   `CreateReduceIndexTableAsync`, both of which take a `collection` — YesSql's
   way of partitioning documents across separate physical tables.

### The part that does not transfer, and how Orchard Core solves it

YesSql index tables are **defined in C# at compile time and created by
migrations**. That is the whole reason its indexes can be strongly typed. Our
Record Types are defined at runtime, from a web form. A type created on
Tuesday cannot have had an index class written for it on Monday.

Orchard Core hits this exact wall — its content types are runtime-defined too
— and its answer is the single most valuable thing to take from this
lineage. It is two layers:

- **`ContentItemIndex`**: one fixed, code-defined index carrying what *every*
  content item has regardless of type — content type, published, latest,
  created date, owner, display text.
- **`OrchardCore.ContentFields.Indexing.SQL`**: for user-defined fields, a
  table **per value kind**, not per field. `TextFieldIndex`
  (`Text nvarchar(766)` + `BigText nvarchar(max)`), `NumericFieldIndex`
  (`decimal(19,5)`), `BooleanFieldIndex` (`bit`), `DateFieldIndex`,
  `DateTimeFieldIndex`, `TimeFieldIndex`, `HtmlFieldIndex`, `LinkFieldIndex`,
  `MultiTextFieldIndex`, `ContentPickerFieldIndex` (`SelectedContentItemId`),
  `UserPickerFieldIndex`. Each row identifies *which* field it indexes with
  three ordinary data columns: `ContentType`, `ContentPart`, `ContentField`.

**The field's identity becomes data instead of a table name.** That is the
whole trick, and it is what makes YesSql's architecture survive contact with
runtime-defined schemas without a single `CREATE TABLE` at request time.

## 4. Storage: one document table

Every record of every type is a row in one `records_record` table with its
field values in a `JSON` column.

This is what YesSql does, and it is independently the right call here:

- `CLAUDE.md` states the invariant plainly: **migrations live in
  `host/migrations/versions/`, never in a module**, and each consuming host
  autogenerates its own revisions from the module's static SQLModel tables. A
  table created per Record Type at runtime produces tables no model describes,
  so the next `alembic revision --autogenerate` in a host proposes to **drop
  every one of them**. Working around that means teaching
  `make_include_object()` a name pattern, after which `SM010`/`SM011` can no
  longer distinguish a missing migration from a dynamic table.
- DDL from an HTTP request races across workers.
- SQLite is the local-dev default, and its narrow `ALTER TABLE` support turns
  any column change into a table rebuild — two divergent evolution paths for
  the two supported backends.

`pagebuilder` already stores whole page trees in `sqlalchemy.JSON` (`json` on
SQLite, `jsonb` on Postgres), so the pattern is proven in this codebase on
both backends under the existing migration story.

## 5. Tables

All under the module's own `Base` (`create_module_base("records")`), all
prefixed `records_`.

### `records_type`

| column | notes |
|---|---|
| `id` | int PK |
| `key` | `str(64)`, **unique**, `^[a-z][a-z0-9_]*$`. Used in URLs, the API, and relation targets. Immutable after creation. |
| `label`, `label_plural` | display names |
| `description`, `icon` | optional; icon is a lucide name |
| `fields` | `JSON` — ordered field definitions, §6 |
| `schema_version` | int, bumped on every change to `fields` |
| `display_field`, `slug_field` | which field supplies `display_title` / `slug` |
| `is_public` | bool, default `False` — gates the anonymous read API |
| `allowed_roles` | `JSON` list of role names permitted to write, §10 |
| + `AuditMixin` | |

`key` is immutable because it appears in URLs, in the public API, and in
relation targets. A rename would strand all three.

`record_count` is **not** a column here. The previous draft denormalised it;
once the index layer exists, `COUNT(*)` against an indexed table is cheap and
cannot go stale.

### `records_record` — the document table

| column | notes |
|---|---|
| `id` | int PK |
| `uuid` | `str(32)`, unique — the identifier used in relations and the public API, so export/import round-trips don't depend on autoincrement |
| `type_id` | int, FK to `records_type`, indexed |
| `data` | `JSON`, non-null, default `{}` — **the payload, never queried** |
| `schema_version` | int — which schema version this row was written against |
| `version` | int, non-null, default 1 — **optimistic concurrency**, §5.1 |
| `status` | enum `draft` / `published`, indexed |
| `slug` | `str(200)`, nullable |
| `display_title` | `str(300)`, denormalised for the list screen |
| `position` | int, for hand-ordered types |
| `published_at` | tz-aware datetime, nullable, indexed |
| + `AuditMixin`, `SoftDeleteMixin` | |

Indexes: `(type_id, status, position)` and a partial unique on
`(type_id, slug)` where `slug is not null`.

These fixed columns are this module's **`ContentItemIndex`** — the projection
every record has regardless of its type, kept on the row itself because a
join to reach "what type is this and is it published" would be on the hot path
of every single query.

`SoftDeleteMixin` is used; `MultiTenantMixin` is not. Deleting content should
be recoverable, and the framework's query filters already exclude soft-deleted
rows with `stmt.execution_options(include_deleted=True)` to bypass. Tenancy is
left off because `MultiTenantMixin.tenant_id` is non-nullable at the DB level,
so adopting it forces multi-tenancy on every host that installs the module —
neither `pagebuilder` nor `news` does this.

#### 5.1 `version` — the gap the previous draft had

YesSql carries `Version` on every document and the previous draft of this
design omitted the equivalent entirely. That is a real defect, not a nicety:
two editors with the same record open in two tabs silently last-write-wins,
and the loser's work is gone with no error and no trace outside the revision
table.

Every write sends the `version` it read. The service issues
`UPDATE … WHERE id = :id AND version = :version` with `version = version + 1`,
and a zero-rowcount result is a **409 Conflict** carrying the current row so
the UI can offer a diff. This is one `WHERE` clause and it removes an entire
category of silent data loss.

### `records_revision`

`(id, record_id, schema_version, version, data JSON, display_title, event,
created_at, created_by)` — append-only, written on every update and delete.

In v1 rather than deferred, because it is the cheapest insurance against the
failure this module is most exposed to: a schema edit or a bad bulk write
mangling content, noticed a week later. Capped per record by `revision_limit`
(§11); unbounded revisions on a busy type outgrow the document table itself.

### The index tables — §7

## 6. Field definitions and validation

### 6.1 A closed field-type set

A field definition is a small object:

```json
{
  "key": "price",
  "type": "number",
  "label": "Price",
  "required": true,
  "unique": false,
  "indexed": true,
  "default": null,
  "help": "Excluding tax",
  "constraints": { "min": 0 },
  "options": null
}
```

`type` comes from a closed set: `text`, `longtext`, `number`, `integer`,
`boolean`, `date`, `datetime`, `select`, `multiselect`, `email`, `url`,
`json`, `media`, `relation`.

**Accepting raw JSON Schema was considered and rejected.** `$ref` makes it a
remote-fetch and cycle-resolution surface; a generic form renderer cannot
render an arbitrary schema, so the UI degrades to a JSON textarea for anything
non-trivial; and arbitrary schemas cannot be diffed, which makes §8
impossible. The escape hatch for genuinely unstructured data is the `json`
field type — which, consistent with §7.2, is not indexable and therefore not
queryable.

### 6.2 Validation by a generated Pydantic model

Each `(type_id, schema_version)` compiles to a Pydantic model via
`pydantic.create_model`, cached per process. Chosen over a `jsonschema`
dependency because it adds **no new dependency**, gives coercion and per-field
error paths for free, and keeps the repo's Pydantic/SQLModel convention.

Two things that make it wrong if missed:

- **The cache key includes `schema_version`.** Keyed on `type_id` alone, a
  schema edit leaves the old validator serving writes against a schema that no
  longer exists.
- **The cache is per process.** A schema edited in worker A is stale in worker
  B. Fixed by reading the type row inside the request that validates and
  keying on the version *that row* reports — never on a version cached
  alongside it.

## 7. The index layer

This is the section the previous draft got wrong, and the reason for the
revision.

### 7.1 What the previous draft proposed, and why it was worse

It deferred indexing to "v2" behind a generic EAV sidecar —
`(record_id, field_key, text_value, num_value, bool_value, date_value)`, one
row with four nullable polymorphic columns — and said meanwhile to filter by
extracting from JSON at query time.

Both halves were wrong:

- **The EAV shape indexes badly.** Four nullable columns in one row means
  every index is mostly NULLs, selectivity is poor, and `num_value` cannot be
  a real `decimal` if it must also be null for every text row without wasting
  width. Orchard Core's shape — **one table per value kind** — gives each a
  single properly-typed, properly-indexed column, and a row exists in a table
  only if it is of that kind.
- **Deferring it was false economy.** The stated trigger ("build it at ~50k
  rows") ignored that retrofitting means a backfill over every record in every
  installation, and that "query works but gets slow" is a worse failure shape
  than "query is not available", because it degrades in production rather
  than failing in development.

### 7.2 The rule

**If a field is not indexed, it is not queryable.** `data` is opaque. No
endpoint filters, sorts, or searches by extracting from it.

This is stricter than the previous draft and better: it makes performance a
property of the schema, visible on the type editor as a checkbox, rather than
a cliff discovered under load. It is exactly YesSql's contract — the document
payload is storage, the index is the query surface.

### 7.3 The tables

One per value kind, following Orchard Core's `*FieldIndex` families. Each
carries the same discriminators, which is what lets runtime-defined fields
work with compile-time tables:

| column | notes |
|---|---|
| `id` | int PK |
| `record_id` | int, FK → `records_record`, indexed, `ON DELETE CASCADE` |
| `type_id` | int — denormalised so a query never joins to filter by type |
| `field_key` | `str(64)` — **which field this row indexes** |
| `status` | mirrored from the record, so a published-only query needs no join |
| *(value column)* | the one typed column, below |

| table | value column |
|---|---|
| `records_index_text` | `value str(512)` indexed + `value_full Text` unindexed — §7.4 |
| `records_index_number` | `value Numeric(19, 5)` |
| `records_index_bool` | `value Boolean` |
| `records_index_datetime` | `value DateTime(timezone=True)` |
| `records_index_ref` | `target_uuid str(32)` + `target_type_id int` — relations, §9 |

Composite indexes on `(type_id, field_key, value)` per table, which is the
shape every filter term actually uses.

A `multiselect` or a to-many `relation` writes **several rows** for one
`(record, field)` — YesSql's 1:N map index, and the reason `field_key` is a
column rather than these being columns on the record.

### 7.4 The truncation trap

Orchard Core splits text into `Text nvarchar(766)` + `BigText nvarchar(max)`
because 766 is an index-key length limit. Postgres has its own (~2704 bytes
for a btree entry); SQLite has none. Carrying the split is right, but the
correctness consequence has to be stated or it becomes a bug:

**An equality match on a truncated index column can return false positives.**
`records_index_text.value` holds the first 512 characters. A filter must
therefore match on `value` — which is the indexed, selective part — *and then
re-check the untruncated `value_full`* when `value_full IS NOT NULL`. Skipping
the second half means two records whose field values differ only after
character 512 are indistinguishable to every query.

### 7.5 Map indexes only — no reduce, for now

YesSql's `ReduceIndex` plus its bridge table is how it maintains aggregates
(count of posts per day) incrementally on write.

**Not in v1, deliberately.** Once §7.3 exists, the aggregates this module
actually needs — records per type, per status, per relation target — are
`COUNT(*)` with a `GROUP BY` against an indexed table, and a maintained
aggregate would be a second source of truth that can drift. Reduce indexes
earn their complexity when the aggregate is over a volume that makes the
count itself too slow, which is a real threshold and a long way from here.

Reconsider when a single type exceeds roughly a million records and a
dashboard needs a live aggregate over all of them.

### 7.6 Index providers — the extension point worth stealing

YesSql's `IndexProvider` is the only place that knows how a document becomes
index rows, which is what makes indexing extensible without touching the
storage layer. The Python equivalent:

```python
IndexProvider = Callable[[Record, RecordType], Iterable[IndexEntry]]
```

The built-in provider projects every field marked `indexed: true`. A module
registers its own via a `records.index_providers` registry to project
something the schema alone doesn't express — a computed bucket, a
normalised sort key, a denormalised value from a related record.

This is a far better seam than the previous draft's `?expand=`, and it is the
thing that would let `news` or a future module query records without this
module knowing they exist.

### 7.7 Reindexing

Index rows are derived; `data` is the source of truth. That means a bug in the
index-maintenance path produces **wrong query results, not slow ones**, which
is the genuine cost of this whole section and the honest argument against it.

The mitigation is the one YesSql and Orchard both ship: a rebuild. A
`records reindex [--type KEY]` command drops and recreates index rows from
documents, runnable per type, batched, and safe to run live because it is
idempotent. §8 calls it on every schema change that alters which fields are
indexed.

## 8. Schema evolution

A schema change on a type holding 10,000 records must never silently corrupt
or orphan them. Every proposed change to `fields` is **diffed against the
current version and classified** before anything is written:

**Additive** — a new optional field, a new `select` option, a relaxed
constraint, a label edit. Applied immediately; existing records are untouched
and the read path fills the missing key from `default`.

**Restrictive** — a new required field, a narrowed type (`text` → `number`), a
tightened constraint, a removed `select` option, a newly `unique` field.
Applied only after a **dry-run validation pass** over the type's existing
records, reporting how many rows would fail with a sample. Refused unless the
caller supplies a `default` that makes every row valid, or `force: true` —
which applies the change and *marks* failing rows rather than mutating them.

**Destructive** — deleting a field. Removed from `fields`; the key is retained
in each record's payload under a reserved `_orphaned` object. Costs storage,
buys back the ability to undo a mis-click that otherwise destroys a column of
content irreversibly. Purged only by a separately-permissioned action.

**Index-affecting** — toggling `indexed`, or any type change on an indexed
field, additionally enqueues a reindex of that `(type, field)` (§7.7). Until
it completes the field is reported as `indexing` and is not offered as a
filter, rather than being offered and silently returning partial results.

Two invariants hold it together:

- **Reads are lenient, writes are strict.** A record stamped at version 3 read
  under version 5 renders with missing keys defaulted and unknown keys
  ignored. Writing it back validates against 5 and restamps. Records migrate
  lazily on edit, never in a bulk job that can half-fail.
- **A record that cannot satisfy the current schema is marked, not hidden.**
  No third `status` value; the list screen derives an "invalid under current
  schema" badge at read time. A row vanishing because someone tightened a
  constraint is what makes people stop trusting the module.

Deleting a Record Type that holds records requires an explicit
`confirm_record_count` matching the actual count.

## 9. Relations

A `relation` field stores `{"type": "<type_key>", "uuid": "<record uuid>"}` in
the payload — and, because of §7.3, also writes a `records_index_ref` row.

That index row is what makes relations useful rather than merely stored. It is
Orchard Core's `ContentPickerFieldIndex.SelectedContentItemId`, and it buys
the thing the previous draft could not answer: **"what references this
record?"** is a single indexed query, so the delete dialog can show it.

- **No automatic expansion.** Reads expand only under an explicit
  `?expand=field_a,field_b`, one batched query per named field, depth 1.
  Depth > 1 is unsupported in v1 and must not be added without a cycle guard.
- **Delete behaviour is a property of the field** — `restrict` (default),
  `set_null`, or `cascade` — enforced in the service, because there is no
  foreign key to enforce it in the DB. `restrict` is the default because a
  cascade default across a user-defined graph deletes content nobody asked to
  delete. With `records_index_ref`, `restrict` is now a cheap check rather
  than a scan.
- Soft-deleting a target leaves referrers pointing at a hidden row. Reads
  resolve it to `null` with `dangling: true` rather than erroring — a
  restorable delete must not break what references it.

## 10. Permissions, and an honest limitation

`register_permissions` runs at app construction, before the database is open.
Record Types are created at runtime. **Per-type permissions therefore cannot
be framework permissions** — there is no point in boot at which the type list
is both known and still registrable.

v1 accepts the consequence:

- Three static permissions — `records.view`, `records.edit`,
  `records.manage_types` — which appear in the role editor and behave
  normally.
- Per-type narrowing via `RecordType.allowed_roles`, enforced in `deps.py` on
  top of the static permission. Empty means "any role holding the static
  permission".

The limitation goes in the README, not buried: **per-type roles are invisible
in the framework's role editor.** An admin editing roles sees three coarse
permissions and will not discover there that Products is restricted to
`editor`.

The alternative — a permission per type registered at boot from a pre-app DB
read, which `_preapp_config` proves is possible — would make a newly created
type require a restart before its permission became grantable. Worse.

### Public read API

Off by default. A type with `is_public = True` exposes
`GET /api/records/public/{type_key}` and `…/{uuid}`, published records only,
with draft rows and audit columns removed from the response shape rather than
filtered in the query.

Registered through `register_public_routes` with methods pinned to
`{"GET", "HEAD"}` — and, because the set of public types is known only after
settings hydration, filled from `on_startup` rather than the
construction-time hook, exactly as `pagebuilder.boot.exempt_public_routes`
does and for the same reason. The `startswith` prefix trap applies: the rule
terminates in `/`, and the fixed `/api/records/public/` prefix cannot match
the admin surface.

## 11. Settings

DB-backed via `register_module_settings`, no environment variables — the rule
`pagebuilder` and `news` already follow.

| setting | default | restart? |
|---|---|---|
| `public_route_prefix` | `/api/records/public` | yes (`_RESTART`) |
| `default_page_size` / `max_page_size` | 25 / 200 | no |
| `revision_limit` | 50 per record | no |
| `max_payload_bytes` | 256 KB | no |
| `max_fields_per_type` | 100 | no |
| `max_indexed_fields_per_type` | 25 | no |
| `reindex_batch_size` | 500 | no |

`max_indexed_fields_per_type` is the one that is easy to omit and expensive to
add later: every indexed field is a row written per record per save, so a type
with 80 indexed fields turns one save into 81 inserts. A visible ceiling makes
that a design conversation at schema-editing time instead of an incident.

## 12. Frontend

Four pages under `sm_records/pages/`, and nothing else in that directory —
`import.meta.glob` derives page names from the path, so a helper dropped there
silently registers a page.

| page | route |
|---|---|
| `Types.tsx` | `/admin/records` — type list |
| `TypeEditor.tsx` | `/admin/records/types/{key}` — schema editor |
| `RecordList.tsx` | `/admin/records/{key}` — generic, schema-driven list |
| `RecordEditor.tsx` | `/admin/records/{key}/{uuid}` — generic, schema-driven form |

`components/fields/` holds one small component per field type behind a
registry map, mirroring `pagebuilder/components/blockRegistry.ts`. The
300-line cap makes this the only workable shape for fourteen field types
anyway.

The schema editor surfaces `indexed` as a first-class checkbox with its
consequence spelled out next to it — filterable and sortable, at the cost of a
write — because §7.2 makes it the single most consequential choice on the
screen.

**Writes go through `fetch()` against `/api/records/*`, never Inertia's
`router.post()`.** `SM018` fires on exactly that pairing, because Inertia
rejects a non-Inertia JSON response. Navigation and flash redirects use
Inertia; mutations use `fetch`.

A **409 from §5.1 must be a real UI state**, not a toast. The editor shows
that the record changed underneath, what changed, and offers reload-or-
overwrite. A concurrency check whose only surface is a red toast trains people
to click through it.

**This module ships `locales/en.json` and uses `t(keys.records.…)` from day
one.** That diverges slightly from `CLAUDE.md`'s note that the three existing
modules should convert together — but that note is about not doing piecemeal
conversions during unrelated work, and is not a reason to add a fourth
module's worth of hardcoded English to the backlog. Zod schemas carrying
translated messages are built inside `useT()`, never at module scope, or they
freeze against the first render's locale.

**Content i18n is out of v1.** `pagebuilder` shows the real cost: locale on
every row, uniqueness per `(locale, slug)`, a `translation_group`,
locale-scoped redirects, and the rule that a page's language is fixed for its
lifetime. Doing that generically for user-defined types is a v2 feature; the
schema leaves room, since adding `locale` and `translation_group` to
`records_record` is additive. What must not happen is a half-version where
records have a locale but slugs aren't scoped to it — precisely how `/de/p/x`
starts serving the English page.

### Collections, deferred

YesSql partitions documents into separate physical tables per *collection*,
and every schema-builder call takes one. The equivalent here is giving a
high-volume type its own document and index tables instead of sharing the
global ones. It is the right escape hatch for one type that dwarfs the others,
and it is not v1 — but `type_id` being on every index row (§7.3) is what keeps
the option open without a migration of the query layer.

## 13. Module wiring

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
`register_routes`, `on_startup` (public-route exemptions, index-provider
registry, settings-dependent wiring).

`view_prefix` points at `/admin/records` directly rather than using
`admin_view_prefix` — every screen here is administrative, so it needs one
router, not two. The `/admin` prefix is a URL convention and not a guard; the
routes carry their permission dependencies regardless.

Menu items are registered without `roles`, matching `pagebuilder`'s reasoning:
role filtering is a plain intersection with no admin bypass, so listing roles
hides the entry from an `admin` user.

## 14. Checklist against `docs/adding-a-module.md`

All ten steps apply. The four most often missed:

- `host/pyproject.toml` — the dependency **and** `[tool.uv.sources...]
  workspace = true`.
- Framework deps as **ranges** (`simple_module_core>=0.0.25,<0.1`), never
  `==`. `version = "0.0.7"` to match `scripts/bump_version.py
  --check-current`.
- `modules/records/tests` in root `testpaths`; a pytest step in
  `.github/workflows/ci.yml`; and `simple_module_records` in the
  `publish-pypi` matrix in `release.yml` — the last is what publishes it.
- The first Alembic revision carries `branch_labels = ("records",)`.

## 15. Tests

The cases that would actually catch a regression:

- Every field type: valid, invalid, missing-and-required,
  missing-and-optional-with-default.
- **Index correctness**: a save writes the expected index rows; an update
  replaces rather than appends them; a delete removes them; a reindex from
  documents produces byte-identical rows to incremental maintenance. That last
  one is the test that catches §7.7's real risk.
- **Truncation**: two records whose text field differs only after character
  512 are distinguishable by an equality filter (§7.4).
- **Concurrency**: two writes from the same read `version` — second gets 409,
  first record is intact, revision table shows one update (§5.1).
- Schema diff classification — one test per additive / restrictive /
  destructive / index-affecting case, asserting the classification itself.
- A restrictive change against records that would fail it: refused without
  `force`; with `force`, marks rather than mutates.
- A record stamped at an old `schema_version` reads leniently and restamps on
  write.
- Validator cache: edit a schema, then write — validates against the *new*
  version.
- `restrict` blocks deleting a referenced record; `set_null` and `cascade` do
  what they say; soft-deleting a target yields `dangling: true`, not a 500.
- `register_public_routes` asserted against the registry directly, as
  `modules/pagebuilder/tests/test_public_routes.py` does. Playwright specs run
  authenticated and will not catch a missing exemption — and here the
  consequence is anonymous read access to unpublished content.
- A private type is unreadable via the public endpoint even by uuid.
- `max_payload_bytes`, `max_fields_per_type`, `max_indexed_fields_per_type`
  are enforced.

## 16. Phasing

**Phase 1 — document + index spine.** Tables (including `version` and the
index tables), migration, field-type set, Pydantic compilation, index
maintenance on write, reindex command, type CRUD, record CRUD, and a
JSON-textarea record editor. Ugly but end-to-end, and it proves the index
layer before any UI is built on it. The index layer is in Phase 1, not bolted
on later, for the reason in §7.1.

**Phase 2 — the UI.** Schema editor (with `indexed`), `components/fields/`
registry, generic list with filter/sort/pagination driven by the index tables,
generic form, 409 conflict handling, `locales/en.json`.

**Phase 3 — safety.** Schema diffing and classification, dry-run validation,
index-affecting reindex enqueue, revisions and restore, trash and restore.

**Phase 4 — reach.** Relations and `records_index_ref` querying in both
directions, `?expand=`, the public read API, `is_public` / `allowed_roles`,
the index-provider registry as a public extension point, README and docs.

Deferred with conditions attached: reduce indexes (§7.5), collections (§12),
content i18n (§12), CSV/JSON import-export, and a `records` widget for
pagebuilder — the last being the natural integration, with `news`'s
`integrations/pagebuilder.py` as the seam to copy.

## 17. What is deliberately not taken from YesSql

Being explicit, so these aren't re-proposed later as oversights:

- **Compile-time typed index classes.** The whole point of the Orchard Core
  layer in §3 is that they can't work for runtime-defined types.
- **A session/unit-of-work abstraction.** The framework already has one:
  `get_db` with its `after_flush` auto-commit and
  `CommitBeforeResponseMiddleware`. `ISession` would be a second, competing
  transaction boundary.
- **`CreateMapIndexTableAsync` / schema-builder migrations.** Index tables
  here are static SQLModel tables in a host Alembic revision, because §4.
- **Reduce indexes and bridge tables.** §7.5.
- **Sharding.** Out of scope at any horizon this repo has.

## 18. Open questions

1. **Does `slug` belong in v1?** Nothing in v1 addresses a record by slug —
   the public API uses `uuid`. Cheap to add later; dead weight if unused.
2. **`display_title` denormalisation** creates a second source of truth that
   goes stale if `display_field` changes. Recomputing every record on that
   edit is a bulk job with exactly the half-failure property §8 avoids.
   Leaning toward recompute-lazily-on-read-if-stale — but note that §7.7's
   reindex already has the batched-rebuild machinery this would need, so
   folding `display_title` into the reindex is probably the answer.
3. **Should `status` really be mirrored onto every index row (§7.3)?** It
   avoids a join on the most common filter and it is a denormalisation that
   must be updated on every publish/unpublish. The alternative is a join to
   `records_record`, which is by primary key and may well be cheap enough.
   Worth measuring in Phase 1 rather than deciding now.
4. **`media` field type** presumes `file_storage` from the framework repo —
   a dependency for one field type. Alternative: a plain `url` field in v1.
