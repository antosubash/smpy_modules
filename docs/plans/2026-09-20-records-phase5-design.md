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
- **No guard on removing a content locale**, and no migration of the records
  left in it. Added after QA: what this *does* do is stop serving them
  publicly — by uuid and in the `translations` list — while leaving them fully
  readable and editable in the admin, and report them as `orphaned_locales` on
  the reindex health check. Moving them into a language the site still
  publishes is a content decision (`POST …/translations` or a delete), not one
  a settings save can make. See §6.6.
- **No `translation_group` in `RecordCreate`, and none an import may invent.**
  The group is a uniqueness exemption, so joining an existing one is
  `POST …/translations` and nothing else. §6.6 has the import rule.

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

### 6.6 As built — where this deviated, and why

Shipped as specified above except for the following. Each is a decision taken
while building, recorded here so the design and the code do not disagree.

**One migration for every host, one for this one.** §6.1 says the host
autogenerates "one migration for the new tables". It is two revisions, and the
split is load-bearing: `records_type.collection` is a nullable column *every*
host needs (`5e2a32dccc22`), and the `records_c_events_*` tables exist only
because this repo's demo host declares that collection (`3b4733cf5444`). A
host that declares none applies the first and skips the second, which is the
§6.5 property expressed in the migration history rather than only in the
metadata. Autogenerate also needs to *see* the declaration, so `host/alembic.ini`
gained `prepend_sys_path = %(here)s` and `env.py` imports `records_collections`
when it exists — a host-level import, not the module-specific one that file's
docstring warns against.

**Index and enum names are derived from the prefix, not only the table names.**
§6.1 says "same indexes". They cannot literally be the same: index names and
Postgres enum type names are schema-global, so `ix_records_record_type_slug`
and `records_record_status` can exist exactly once. Every such name is built
from the table prefix, which is why the DDL test compares modulo the prefix
rather than literally. The one thing that cannot be rewritten that way is a
generated *foreign-key constraint* name, which the framework's naming
convention truncates with a hash once the table name grows past Postgres's
63-byte limit; the test elides that name and compares the FK's shape.

**Collection names are bounded and partly reserved.** §6.1 gives
`TYPE_KEY_PATTERN` and ≤ 32. Added: `default`, `global`, `records`, `type`,
`index` and `reduce` are refused, the first two because they are what a reader
would expect to mean "the shared tables" — which is the one thing that has no
name — and the rest because `records_c_type_record` reads as a table about
types.

**Referrers is a loop, and the design's "union or loop" is settled as a loop.**
§6.3 says a ref row "stores `target_uuid` and `target_type_id`; the referrers
query already resolves the type". It does — but the `record_id` a reference
table returns is an id in *that set's* record table, and two collections number
their records independently. A `UNION` would merge ids that mean different
rows. So `referrers()` asks one table set at a time and keeps each set's ids
with that set's class; for the same reason the identity of a referring record
is `(collection, id)` rather than `id`, in the `_distinct_records` count and in
the cascade's visited set.

**Per-record helpers resolve their table set from the record's class.** §6.3
says every place that names `Record` "takes its tables from `TableSet`". Three
places hold a row and no type — the revision writer, the revision trim and the
purge — and threading a `TableSet` into them would have changed signatures the
whole module calls. They use `tables_of(record)` instead, a reverse lookup from
the generated class, which cannot disagree with the row about where it came
from because the class *is* the table.

**Type annotations still say `Record`.** The generated classes are siblings of
the global one, not subclasses, so an annotation naming `Record` documents the
shape rather than the table. The one place that mattered was an
`isinstance(current, Record)` in the 409 body builder, which now asks
`table_sets()`.

**`uuid` is globally unique, and enforced on import.** §6.4 says "`uuid`
remains globally unique across collections" and then leaves it to uuid4
("collisions are not a practical concern — say so"). The QA pass showed that
reading is not survivable: the importer keeps a file's uuid verbatim so a round
trip is idempotent (§2), so *exporting a global type and importing it into a
collection type* — the §12 motivation for collections — plants a collision
deterministically. And a collision was not harmless. `referrers()` predicated
on `target_uuid` alone, ignoring the `target_type_id` §6.3 says the query
"already resolves", so the collection's record inherited the global record's
referrers: `restrict` refused a delete nothing pointed at, `cascade` trashed an
unrelated record and `set_null` blanked its field. `check_targets` merged a
uuid → type map across sets with `.update()`, so the *last* set asked won and
a live record stopped being of its own type for every future relation write.

So deviation 8 is amended in both directions. The rule is that a `uuid` is
unique across every table set, and the importer enforces it: a row creating a
record under a uuid any other set holds is a **row error** in the planning
pass, named with the collection (or "the global set") holding it, so a dry run
predicts it and `abort` refuses before writing. The practical consequence is
that moving a type's records into a collection is purge-then-import in that
order, which the README states. Independently of the data, every lookup keys
on `(target_type_id, target_uuid)` and resolves the table set from the type —
`referrers`, `referrer_count`, the delete plan's three behaviours,
`check_targets` and `expand` — so a duplicate that reaches the database some
other way still cannot make one record's delete act on another's.

**A translation group is a capability, and an import may not forge one.**
§4.3 makes `(translation_group, locale)` unique and §5 exempts siblings from
each other's `unique` claims; §2 has the importer carry the group verbatim.
Together those let a hand-written file put an unrelated record into an existing
record's group and hold a `unique` value twice. A creating row may therefore
name only a group it is entitled to: its own `uuid`, one another row of the
same file also carries, or one this type does not hold yet. The unique index
also gained `type_id` as its leading column (`fe3ea2dfe0fb`), because §4.3's
rule is stated per type and every reader of a group scopes by type — without
it, an import into one type was refused by a record of another, in a message
naming a record that did not exist.

**A decommissioned content locale.** §4.2 validates `content_locales` for
non-emptiness and for containing the default, and nothing guards *removing* a
tag that records are written in — unlike §4.1's `translatable` flip, which is
refused. Removing it stays unguarded (the records are good records, and a
refusal makes a typo unfixable), but the three surfaces now agree: the public
API does not serve such a record by uuid and does not list it as a sibling, the
admin API reads and edits it exactly as before, and the reindex health check
carries an `orphaned_locales` count. That count is computed at `on_startup`
only — the framework's settings registry exposes no post-hydration hook.

**The seeder's sixth type.** `event` is declared with `collection="events"` and
created only where that collection is declared. Its share of `--records N` is
taken *proportionally* from the five rather than added on top, so `N` still
means `N` either way — which is the §6.5 property as the seeder sees it.

## 7. Sequencing

Waves, because these rewrite the same files:

1. Perf (F4–F11), import/export, widget — disjoint, in parallel.
2. Content i18n — model, migration, services, public API, frontend.
3. Reduce indexes — writer, reindex, registry, aggregate endpoint, CLI verify.
4. Collections — the table-set refactor, last, because it touches everything
   the earlier waves wrote.
5. QA pass over all of it (API, browser, perf re-run), then fixes.

Each wave is committed and CI-green before the next starts, on the same PR.
