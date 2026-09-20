# Records module — Phase 5: the deferred list

*Addendum to [2026-09-19-records-module-design.md](2026-09-19-records-module-design.md).
That document's §16 deferred six things "with conditions attached". This one
decides how each is built now, and records where the original conditions were
not met so the reader knows the trade was made on request rather than on
evidence.*

## 0. Honest framing

Three of the six were deferred with a **threshold**, not a doubt:

| item | the original condition | met? |
|---|---|---|
| reduce indexes (§7.5) | "a single type exceeds roughly a million records and a dashboard needs a live aggregate" | no — the largest measured dataset is 100k, all on SQLite |
| collections (§12) | "one type that dwarfs the others" | no — no such deployment exists yet |
| content i18n (§12) | "a v2 feature" — a cost statement, not a threshold | n/a |

The other three — import/export, the pagebuilder widget, the open perf
findings — were deferred for **time**, and there is no argument against
building them.

Building the first three ahead of their thresholds is a deliberate choice by
the module's owner. The cost is code that must be maintained before it earns
its keep. The mitigation is that each is **opt-in per type or per host, off
by default, and inert when unused**: a host that never sets `collection` on a
type, never registers a reduce provider, and never enables a second content
locale runs exactly the Phase 4 code paths. Every design below is checked
against that property.

## 1. The open perf findings (F4, F5, F9, F10, F11)

Decided and delegated with these rules; recorded here so the numbers in
`modules/records/docs/performance.md` have a design to point at.

- **F4** `total` is exact up to `max_count` (default 10,000) and then reported
  as `max_count` with `total_capped: true`; `?total=false` skips the count.
  The UI shows "10,000+". An unbounded count is O(matches) whatever the index
  does, and a filter matching most of a large type will always pay it.
- **F5** A single-valued indexed field sorts by a direct outer join on its
  index row (unique by construction); the `MIN` aggregate stays only for
  multi-valued fields. Fixed-column sorts get `(type_id, column, id)` indexes
  and drop `nulls_last` where the column is `NOT NULL`, so the index can serve
  the order.
- **F9** `(type_id, display_title, id)` is indexed and the relation picker
  asks `starts_with` first, `contains` only when that returns under five rows.
- **F10** `POST /schema/preview` is synchronous up to `preview_sync_limit`
  records (default 5,000) and a 202 job above it, run through the module's
  deferred-job middleware and polled at `GET …/schema/preview/{job}`. A `PUT`
  may reuse a completed job's report when the type's `version` has not moved,
  which is what makes reuse safe: the report was computed against exactly
  this schema and this record set's version fence.
- **F11** `?after=<cursor>` keyset pagination on the list API, cursor bound to
  the sort it was produced under (a mismatch is a 400). `page` stays for the
  admin UI; the cursor is for exports and widgets.

## 2. Import / export

- Export streams (keyset by `id`, never a list in memory): JSON as
  `{type: {key, schema_version, fields}, records: [...]}` and CSV per RFC 4180
  with one column per declared field plus `uuid`, `slug`, `status`,
  `position`, `published_at`. Payloads are the lenient read (`read_view`,
  defaults filled) with `_orphaned` stripped — the file is what a reader
  sees, not the undo buffer.
- Import parses everything, validates every row with the compiled validator
  and the relation-target check **before** writing, defaults to a dry run,
  and writes through `create_record` / `update_record` — never a bulk insert,
  because revisions, index rows, uniqueness, slug claims and the type lock are
  what make a record a record. `on_error=abort` is one transaction.
  `upsert` by `uuid` is idempotent: importing an export twice changes nothing.
- Schema export/import goes through `update_type`, so a restrictive import on
  a populated type is refused with the §8 report exactly like the editor.
- CLI `export` / `import` mirror the endpoints.

## 3. The pagebuilder widget

A `RecordsList` Puck block registered from `sm_records/puck-blocks.ts`, the
seam `news` uses: records knows about pagebuilder, pagebuilder knows nothing
about records. It renders from the **anonymous read API** only, so it can show
nothing the public API would not — a private type renders the empty state.
Author-facing props: type, fields to show, filter, sort, limit, layout, link
template. No expansion (the public API has none); relations show as stored.

## 4. Content i18n

The original doc named the cost precisely: "locale on every row, uniqueness
per `(locale, slug)`, a `translation_group`, locale-scoped redirects, and the
rule that a page's language is fixed for its lifetime", and warned against the
half-version "where records have a locale but slugs aren't scoped to it". This
design pays the whole cost and copies pagebuilder's shape, which has already
survived a QA campaign of its own.

### 4.1 Model (additive, one migration)

`records_record` gains:

| column | type | notes |
|---|---|---|
| `locale` | `str(16)`, not null, default `"en"` | the record's language, fixed for its lifetime |
| `translation_group` | `str(32)`, not null, index | siblings share it; a record with no siblings is alone in its own group (`uuid` at creation) |

The partial unique slug index becomes `(type_id, locale, slug) WHERE slug IS NOT NULL`
— **the** change that makes this a full version rather than the half one. The
`records_index_*` tables are untouched: locale is a property of the document,
and a filter on it is a fixed-column predicate (`locale:eq:de`), so `locale`
joins `FIXED_COLUMNS` and is reserved as a field key like every other document
column (`RESERVED_FIELD_KEYS` derives from the model, so this is automatic —
the TypeScript mirror test will fail until `rules.ts` is updated, which is the
point of that test).

`records_type` gains `translatable: bool = False`. A type that is not
translatable has every record in the default content locale and shows no
language UI. Flipping it on is additive (existing records already carry the
default locale); flipping it **off** while non-default-locale records exist is
refused (409) — otherwise those records become unreachable through a UI that
no longer offers their language.

### 4.2 Settings

`RecordsSettings.content_locales: tuple[str, ...] = ("en",)` and
`default_content_locale: str = "en"`, both `_RESTART` (they shape routes and
the reserved-column set), validated as pagebuilder validates its own (default
must be in the list, at least one). **Deliberately the module's own setting,
not pagebuilder's**: records must not depend on pagebuilder, and the two
modules may legitimately publish in different language sets. The README says
so, and says that a host wanting them aligned sets both.

### 4.3 Rules

- **A record's language is fixed for its lifetime.** No `locale` in
  `RecordUpdate`; the column is set at create (from `RecordCreate.locale`,
  default the default content locale, must be in `content_locales`) or by
  `POST /records/{uuid}/translations {locale}` which creates a sibling: same
  type, same `translation_group`, status `draft`, payload copied, slug
  regenerated **in the new locale** (so it never collides across locales,
  and never silently inherits the source's address), `position` copied.
- **One record per `(translation_group, locale)`** — enforced by a unique
  index; a second translation into the same language is a 409.
- **Every slug lookup takes a locale.** `get_by_slug`, `ensure_slug_free`,
  the DB-level `IntegrityError` mapping, the public API, the widget's link
  template — all of them. The original doc's warning is the acceptance test:
  a `de` record must never be served for the `en` slug.
- **Trash keeps its claim per locale**, unchanged from Phase 1's rule.
- **Deleting a record does not touch its siblings.** A translation group is
  not a cascade; it is a grouping.
- `allowed_roles`, `is_public`, `on_delete` are type-level and locale-blind.

### 4.4 API and UI

- `RecordRead` gains `locale`, `translation_group`, and — only under
  `?translations=true` or on the editor view — `translations: [{locale,
  uuid, status, display_title}]` for the siblings (one query per record read,
  never on the list).
- The list accepts `?locale=` (a fixed-column filter with a UI selector); the
  admin list defaults to **all locales** with a locale column, because an
  editor's question is "what exists", not "what exists in English".
- The public API: `GET {prefix}/{type}?locale=de` filters; **no locale means
  the default content locale**, never "all" — an anonymous reader asks for
  one site. `GET {prefix}/{type}/{uuid}` is locale-blind (a uuid is one
  record). The public shape gains `locale` and `translations: [{locale, uuid,
  slug}]` so a site can render a language switcher; only **published**
  siblings are listed there.
- The editor grows a Languages panel modelled on news' `ArticleTranslations`:
  one row per content locale — "Editing", "Open", or "Add" — with the same
  disable-until-siblings-known rule that panel documents.
- The widget gains a `locale` prop (default: the site's default content
  locale).

### 4.5 What this does not do

- No per-field translation. A translation is a whole sibling record. This is
  what pagebuilder and news do, and mixing the two models is the mistake the
  original doc's "half-version" warning is about.
- No locale-scoped **redirects**: records have no public *pages*, only a JSON
  API keyed by uuid and slug, so a rename does not strand a URL the way a
  page rename does. If the widget's link template ever becomes a router, add
  them then.
- No automatic translation, no fallback to the default locale on the public
  API (a missing `de` sibling is a 404 for `?locale=de`, not the `en` record
  in disguise).

## 5. Reduce indexes (§7.5)

The original argument against a maintained aggregate was **drift**: a second
source of truth. This design keeps that argument and answers it with a
verifier instead of pretending the risk away.

### 5.1 Two things, clearly separated

- **Aggregation over the map indexes**, always available, never stored:
  `GET /api/records/types/{key}/records/aggregate?group_by=<indexed field or
  fixed column>&metric=count|sum:<number field>|min|max&filter=…` → a
  `GROUP BY` over the index table with the same semi-join filter the list
  uses. This is the "`COUNT(*)` with a `GROUP BY` against an indexed table"
  the original doc said would serve every real need. It is what the admin
  dashboard card uses. `allowed_roles` applies; the public API does not get
  it (an anonymous aggregate is an oracle over private rows).
- **A reduce index**, opt-in per provider: YesSql's `ReduceIndex` — an
  aggregate maintained incrementally on write for a volume where the `GROUP
  BY` is too slow. One table, `records_index_reduce(type_id, key,
  group_value, count, sum, updated_at)`, unique on `(type_id, key,
  group_value)`.

### 5.2 The reduce provider seam

```python
from sm_records.index import register_reduce_provider, ReduceSpec

register_reduce_provider(ReduceSpec(
    key="orders_per_state",          # a virtual key; reserved like any provider key
    group_by=lambda record, rtype: record.data.get("ship_state"),
    value=lambda record, rtype: Decimal(record.data.get("total") or 0),
))
```

- **Maintained by delta, inside the write transaction**: `write_index` reads
  the record's previous projection (the row it is about to replace), computes
  `(group, value)` before and after, and applies `-1/+1` and `-old/+new` to
  the affected group rows with `UPDATE … SET count = count + :d` (an upsert
  on first sight). No read-modify-write in Python, so two writers cannot
  lose an increment; on SQLite the type-row lock already serialises writers,
  on Postgres the row-level `UPDATE` does.
- **Rebuilt by reindex**: `reindex_type` truncates the type's reduce rows and
  recomputes them from the map projection in one `INSERT … SELECT … GROUP
  BY`. So the reduce table is always derivable from the map tables, which is
  the property YesSql's bridge table exists to keep.
- **Verified**: `python -m sm_records.cli reindex --verify` recomputes the
  aggregate from the map tables and reports every group that disagrees with
  the stored row; the health check gains a `reduce_drift` detail when a
  verify has ever failed for a type until the next successful rebuild. Drift
  is therefore *detectable*, which is the honest answer to §7.5's objection.
- **Read**: `GET …/records/aggregate?reduce=orders_per_state` returns the
  stored rows; the same endpoint, so a caller can switch between the live
  `GROUP BY` and the maintained aggregate and compare.
- A reduce provider's `key` is a virtual key (reserved, validated, owned)
  and is refused as a declared field like every provider key.

## 6. Collections (§12)

YesSql's collection is a physical partition: its own document and index
tables. The original doc kept the option open by putting `type_id` on every
index row "without a migration of the query layer". This design cashes that
in with the smallest possible surface.

### 6.1 Declaration is code, not configuration

Tables must exist in the host's Alembic history, so a collection cannot be a
DB-backed setting read at boot. It is declared by the **host** in code:

```python
# host/records_collections.py, imported by host/main.py before create_app
from sm_records.collections import declare_collection
declare_collection("events")
```

`declare_collection(name)` (name: `TYPE_KEY_PATTERN`, ≤ 32) creates, on the
module's own `MetaData`, a full table set with the prefix
`records_c_<name>_`: `record`, `revision`, and the six index tables, each
identical in shape to the global one (same columns, same indexes, same partial
unique slug index, same FKs, pointing at the collection's own record table).
The host then autogenerates one migration for the new tables, exactly as it
did for the module itself. Declaring after app construction is an error;
declaring twice is idempotent.

### 6.2 Assignment is per type, at creation only

`records_type.collection: str | None` (default `None` = the global tables).
Set only on `POST /types` — **moving a populated type between collections is
not supported** (it would be a data migration with no rollback story; the
refusal is a 409 with that sentence). The type editor shows the collection as
read-only after creation, and the "new type" form offers the declared
collections.

### 6.3 One query layer, parametrised by table set

`sm_records.models.tables_for(rtype) -> TableSet` returns the global set or
the collection's. Every place that names `Record`, `RecordRevision` or an
`INDEX_TABLE[kind]` takes its tables from `TableSet` instead — the writer,
the query builder, the reindex, the dry run, the orphaned sweep, the
referrers query, expansion, export/import, the seeder. The ORM classes for a
collection are generated by the same factory that builds the global ones, so
the SQLModel/soft-delete/audit behaviour is identical by construction, and a
test asserts the DDL of a collection's tables equals the global DDL modulo
the prefix.

Cross-collection relations are allowed (a ref row stores `target_uuid` and
`target_type_id`; the referrers query already resolves the type, and now
resolves the table set from it). `?expand=` across collections is one
batched query per field as before — the target type decides the table.

### 6.4 What stays global

`records_type`, `records_type_revision`, the reduce table (keyed by
`type_id`), settings, permissions, the health check, the CLI (it takes a
type and follows its collection). `uuid` remains globally unique across
collections (each record table has its own unique index; the seeder and
import generate uuid4, so collisions are not a practical concern — say so).

### 6.5 Inert when unused

With no `declare_collection` call the module's metadata is byte-identical to
Phase 4's, no migration is generated, and `tables_for` always returns the
global set. That is the acceptance test for "opt-in".

## 7. Sequencing

Waves, because these rewrite the same files:

1. Perf (F4–F11), import/export, widget — disjoint, in parallel.
2. Content i18n — model, migration, services, public API, frontend.
3. Reduce indexes — writer, reindex, registry, aggregate endpoint, CLI verify.
4. Collections — the table-set refactor, last, because it touches everything
   the earlier waves wrote.
5. QA pass over all of it (API, browser, perf re-run), then fixes.

Each wave is committed and CI-green before the next starts, on the same PR.
