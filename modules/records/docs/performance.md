# Records — performance

What this module costs at scale, measured, and what to watch for. The full
study that found these — raw output, query plans, every command — is
[`perf-study-2026-09-19.md`](perf-study-2026-09-19.md); this is the
maintainer's copy, and it is the one that says what has since been **fixed**.

**Measured on:** SQLite 3.45.1 (file-backed, `journal_mode=delete`, no
`ANALYZE` unless stated), aiosqlite 0.22.1, SQLAlchemy 2.0.51, Python 3.12,
single process, HTTP driven in-process through `tests/app_harness.py`. **No
Postgres was available**, so every number is SQLite; §"On Postgres" says which
findings should reproduce there.

**Datasets.** The original study ran at 100,000 records. The before/after
tables below are the durable suite at its two reproducible sizes,
`RECORDS_PERF_N=2000` and `RECORDS_PERF_N=20000`, seeded by `sm_records.seed`
into the five demo types (`order` 45%, `contact` 25%, `product` 15%, `store`
10%, `company` 5%). At 20,000 that is 9,000 orders, 5,000 contacts, 3,000
products, 2,000 stores and 1,000 companies. The two runs of each pair start
from **byte-identical copies of one seeded file**, so a row of a table below
is one code change and nothing else.

## Run the suite yourself

```
cd modules/records && RECORDS_PERF_N=<n> ../../.venv/bin/python -m pytest -q -s -m perf tests/perf -p no:cacheprovider
```

It is excluded from the default run (`addopts = "-m 'not perf'"`), and `-s` is
load-bearing: the results table is printed from a session fixture, so pytest
captures it without it. `RECORDS_PERF_N` sets the dataset size (default 2000,
about a minute), `RECORDS_PERF_REPS` the repetitions (default 20),
`RECORDS_PERF_BUDGET` the seconds one measurement may spend, and
`RECORDS_PERF_DB` points it at a database seeded elsewhere. A database seeded
before a revision added an index picks it up on the next run — `create_all` is
`checkfirst` per *table* and would otherwise keep measuring the old schema
against the new code. It prints a results table and the
`EXPLAIN QUERY PLAN` of each operation's heaviest statement — which since F4
is often the bounded count rather than the page, so a *page* plan is worth
taking by hand — and asserts only shapes: "a filtered list does not full-scan
`records_record`", "a create issues no index `DELETE`s", "a page costs a
constant number of statements", "`total=false` costs one statement less".
Never wall-clock thresholds.

## Fixed

All eleven findings. Each row is p50 over 20 repetitions on the same seeded
file, before → after.

The F4/F5/F9/F10/F11 pairs below were taken in two runs **back to back on one
machine**, each from its own copy of the same seeded file, the "before" run
against a detached worktree at the commit before the change. Read the
control rows with them: `count_query(order, ship_state=CA)` (0.99 → 1.05 ms)
and `GET one order by uuid` (4.02 → 4.10 ms) are code neither run touched, and
they say what the machine's own drift was worth.

### F1 — a filter was correlated per record; it is now a semi-join

`index/query.py` emitted `EXISTS (SELECT 1 FROM idx WHERE idx.record_id =
records_record.id AND …)` — a subquery that is a function of the outer row, so
its cost was (records of the type) × (work per probe). With no `sqlite_stat1`
SQLite drove it from the *value* index and re-filtered the whole matching range
by `record_id` once per record of the type, which is where a single list page
of 25 took nine seconds over 9,000 orders. It is now
`Record.id IN (SELECT record_id FROM idx WHERE type_id = … AND field_key = …
AND <value predicate>)`, which runs **once**, from the rows that match.

| filter | 20,000 records | | | 2,000 records | |
|---|---|---|---|---|---|
| | before | after | | before | after |
| `placed_at:gte:…`, 9,000 orders | 9,258.26 ms | **18.89 ms** | 490× | 82.11 ms | **9.58 ms** |
| three ANDed filters, 9,000 orders | 13,777.07 ms | **40.26 ms** | 342× | 208.52 ms | **10.95 ms** |
| `price:gte:100`, 3,000 products | 1,264.70 ms | **13.19 ms** | 96× | 21.76 ms | **8.67 ms** |
| `in_stock:eq:true`, 3,000 products | 581.07 ms | **10.64 ms** | 55× | 15.60 ms | **8.53 ms** |
| `founded:gte:1990-01-01`, 1,000 companies | 123.97 ms | **9.76 ms** | 12.7× | 12.19 ms | **8.71 ms** |
| `ship_state:eq:CA` (select), 9,000 orders | 26.64 ms | **9.55 ms** | 2.8× | 9.77 ms | **8.04 ms** |
| `customer:eq:<uuid>` (ref), 9,000 orders | 26.98 ms | **5.72 ms** | 4.7× | 7.20 ms | **7.41 ms** |
| `city:eq:…` (text), 1,000 companies | 8.33 ms | **5.56 ms** | 1.5× | 9.28 ms | **8.68 ms** |
| `count_query(order, ship_state=CA)` alone | 11.05 ms | **1.04 ms** | 10.6× | 1.60 ms | **0.78 ms** |

The plans, at `RECORDS_PERF_N=2000`:

```
  before: GET company list, text eq (city)
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
    CORRELATED SCALAR SUBQUERY 1
    SEARCH records_index_text USING INDEX ix_records_index_text_record (record_id=?)
  after:
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=? AND rowid=?)
    LIST SUBQUERY 1
    SEARCH records_index_text USING INDEX ix_records_index_text_lookup (type_id=? AND field_key=? AND value=?)

  before: GET order list, datetime range gte (placed_at)
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
    CORRELATED SCALAR SUBQUERY 1
    SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=? AND value>?)
  after:
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=? AND rowid=?)
    LIST SUBQUERY 1
    SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=? AND value>?)

  before: GET order list, 3-filter AND
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
    CORRELATED SCALAR SUBQUERY 1
    SEARCH records_index_number USING INDEX ix_records_index_number_lookup (type_id=? AND field_key=? AND value>?)
    CORRELATED SCALAR SUBQUERY 2
    SEARCH records_index_text USING INDEX ix_records_index_text_record (record_id=?)
    CORRELATED SCALAR SUBQUERY 3
    SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=? AND value>?)
  after:
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=? AND rowid=?)
    LIST SUBQUERY 1
    SEARCH records_index_number USING INDEX ix_records_index_number_lookup (type_id=? AND field_key=? AND value>?)
    LIST SUBQUERY 2
    SEARCH records_index_text USING INDEX ix_records_index_text_lookup (type_id=? AND field_key=? AND value=?)
    LIST SUBQUERY 3
    SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=? AND value>?)
```

`CORRELATED SCALAR SUBQUERY` → `LIST SUBQUERY` is the whole finding: the
subquery stopped being a function of the outer row, and the outer table is now
reached by rowid rather than scanned.

The semantics are unchanged and `tests/test_index_query.py` is what says so.
`ne` and `is_null` are the negation of the **whole** semi-join (`NOT IN`), not
a predicate over one row — on a multi-valued field "no value equals x" is the
only correct reading of `ne`, and `eq` is the `any` reading, which `IN` gives
directly because it deduplicates. `record_id` is `NOT NULL` on every index
table, which is what makes `NOT IN` safe. The §7.4 truncation re-check lives in
the value predicate and was not touched.

**`ANALYZE`, where the module can legitimately own it.** The semi-join removes
the planner's *chance* to get this wrong, and statistics still make its other
choices informed. Two moments are the module's to claim, and neither is a
request: the end of a completed reindex (`services/reindex_runner.py`, the
tables the rebuild wrote) and the end of a `seed` run (`seed/runner.py`, the
module's own tables). Both are SQLite-only and best effort —
`index/_analyze.py` swallows a refusal, because a rebuild that finished
correctly must not be reported as failed, nor retried from the top, because a
statistics pass lost a race for the write lock. Nothing on a request path runs
`ANALYZE` or a `PRAGMA`.

### F2 — `ensure_unique` was O(rows in the type)

`services/_payload.ensure_unique` (now `services/_claims.py`) asked
`count_query` — the list page's `COUNT`, with no `LIMIT`, over every record of
the type — to answer "is this value taken". It now builds the same filter with
the same `_term` and asks `exists_query`: `SELECT records_record.id … LIMIT 1`.
`exclude_id`, `include_deleted`, the §7.4 truncation re-check and the
"built inside the `try` so a `reindex_pending` field is our 409" structure are
unchanged.

Measured directly, one type holding **20,023 rows**, same database file, same
field, warm:

| | before | after |
|---|---|---|
| `ensure_unique` (`unique` text field, no match) | **16.06 ms** | **0.87 ms** |

Plan after: `LIST SUBQUERY 1 / SEARCH records_index_text USING INDEX
ix_records_index_text_lookup (type_id=? AND field_key=? AND value=?)`, then
`SEARCH records_record USING COVERING INDEX ix_records_record_type_id`.

And the curve is gone. `product` has a unique `sku`; `company` has no unique
field and is the control:

| create, p50 | 2,000 records (300 products) | 20,000 records (3,000 products) | growth |
|---|---|---|---|
| `create_record(product)` **before** | 15.96 ms | 20.21 ms | +4.25 ms |
| `create_record(product)` **after** | 11.13 ms | **10.89 ms** | **−0.24 ms** |
| `create_record(company)` before | 14.75 ms | 15.97 ms | +1.22 ms |
| `create_record(company)` after | 10.28 ms | **10.74 ms** | +0.46 ms |

A create on the type with the unique field now costs what a create on the type
without one costs, at both sizes.

### F3 — concurrent creates with the same unique value all succeeded

Two independent defects, both fixed, both pinned by
`tests/test_unique_concurrency.py` — which insists on a **file-backed**
database on the **default pool** for the reason `test_reindex_runner_locking`
does: on the shared-connection `:memory:` harness every session is one
transaction, so check-then-act cannot be caught there at all.

* `_claims.lock_type` issued `SELECT … FOR UPDATE`, which is a row lock on
  Postgres and **nothing** on SQLite. The reasoning that "the database is
  single-writer anyway" missed that SQLite is single-*writer*, not
  single-*transaction*: eight read-only checks all passed, then eight inserts
  took the write lock in turn. It now branches on
  `db.get_bind().dialect.name`: `UPDATE records_type SET version = version
  WHERE id = :id` on SQLite, which takes the `RESERVED` lock at the top of the
  write path and holds it for the rest of the transaction, so the second writer
  blocks *before* its check rather than after it. `SET version = version` is a
  deliberate no-op assignment — it must not move the value optimistic
  concurrency compares against, and it must still be a write. `FOR UPDATE`
  stays on every other dialect.
* A slug collision that the application check lost the race for surfaced as an
  unhandled `IntegrityError`, i.e. HTTP 500. `_claims.flush_write` now wraps
  the record flush and raises the *same* `Conflict` (409)
  `_claims.ensure_slug_free` raises, recognised by
  `models.SLUG_CONFLICT_SIGNATURES` — the index name (Postgres) or the column
  pair (SQLite, which never names the index). Anything else is re-raised.
  `rtype.key` is read before the flush: a failed flush expires the session, so
  reading it afterwards turned the 409 into a `PendingRollbackError`.

| 8 concurrent creates, same unique value | before | after |
|---|---|---|
| `contact.email` (unique, not the slug field) | 8× `201`, **8 rows stored** | **1× `201`, 7× `409`, 1 row stored** |
| `product.sku` (unique *and* the slug field) | 1× `201`, 3 unhandled `IntegrityError` (500) | **1× `201`, 7× `409`, 1 row stored** |

Eight *different* unique values under the same lock are still eight rows: the
serialisation costs throughput, not correctness, and that is asserted too.

### F6 — `write_index` deleted six times on every create

`index/writer.write_index` takes `fresh: bool = False`; `create_record` passes
`fresh=True` and the six `DELETE FROM records_index_*` are skipped. The default
is the safe, unconditional behaviour, because being wrong about it leaves
*duplicate* index rows — a wrong answer, not a slow one (§7.7) — and only a
caller that inserted the row in this transaction can assert it. The perf suite
now asserts a create issues no index `DELETE`s at all.

### F7 — `type_id_map` read all of `records_type` twice per write

`services/records._prepare` resolves `{key: id}` once and returns it in a
`_Prepared` tuple; the relation check and the index writer's resolver share it.
Threaded through an argument rather than cached on the module: types are
created and deleted at runtime, and a stale id in `records_index_ref` is what
`on_delete` is enforced from. The suite asserts one read per create.

Together F2 + F6 + F7 take a create from **20 statements to 13**, at every
table size:

| write | before | after |
|---|---|---|
| `create_record`, no unique field | 14.75 → 15.97 ms, 20 statements | **10.28 → 10.74 ms, 13** |
| `create_record`, unique field | 15.96 → 20.21 ms, 21 statements | **11.13 → 10.89 ms, 14** |
| `update_record` (indexed field changed) | 16.20 → 20.89 ms, 22 statements | **14.82 → 15.03 ms, 21** |
| trash → restore → trash → purge | 42.61 → 44.14 ms, 53 statements | **38.07 → 36.95 ms, 46** |

(An update still deletes before it writes — it has to.)

### F8 — the reindex wrote one record at a time

`index/reindex.reindex_batch` rewrites a whole batch: one
`DELETE … WHERE record_id IN (:batch)` per index table, then one
`session.execute(insert(Table), rows)` per table. `after_batch` still commits
per batch — that is what bounds SQLite's write lock — and `_clear_rebuilt`'s
semantics are untouched. The projection is shared with the incremental writer
(`writer.project` / `writer.row_values`), so a rebuilt row is byte-for-byte
what an ordinary write produces; `tests/test_index_reindex.py` compares the two
snapshots and is what says so.

| rebuild of the `store` type | before | after | |
|---|---|---|---|
| 2,000 records, `reindex_batch_size` 100 | 14,790 ms — 135 rec/s | **611 ms — 3,275 rec/s** | 24× |
| 2,000 records, 500 | 14,960 ms — 134 rec/s | **451 ms — 4,430 rec/s** | 33× |
| 2,000 records, 2000 | 19,775 ms — 101 rec/s | **448 ms — 4,463 rec/s** | 44× |
| 200 records, 500 | 1,419 ms — 141 rec/s | **52 ms — 3,822 rec/s** | 27× |
| `display_field` change (2,000, whole-type) | 15,867 ms — 126 rec/s | **754 ms — 2,654 rec/s** | 21× |

`reindex_batch_size` now does something: bigger is better, and 2000 is no
longer *worse* than 100. The 45,000-record `order` type that spent ~6 minutes
refusing its filters with a 409 after an index-affecting change is now well
under thirty seconds of that at these rates.

### F4 — every list page computed an unbounded total

`total` is now exact up to `RecordsSettings.max_count` (new, default 10,000)
and reported as that ceiling with `total_capped: true` beyond it — the list
screen renders "10,000+". `index.query.bounded_count_query` is the count with
`LIMIT cap + 1` inside it, and `?total=false` skips the statement entirely
(`total: null`), which is what a caller paging with `?after=` should send.

| | before | after |
|---|---|---|
| count of 9,000 orders, bound at 3,000 | 3.01 ms | **1.84 ms** |
| count of 9,000 orders, bound at 18,000 (above the type) | 3.01 ms | 3.78 ms |
| `GET /order/records` (3 statements) | — | 15.00 ms |
| `GET /order/records?total=false` (**2** statements) | — | **8.53 ms** |
| the same page with `max_count = 3000` | — | 11.72 ms, `total: 3000` |

Two honest costs. The bound is **O(cap), not O(matches)** — so on a type
*below* the ceiling it is the same work plus a trivial outer aggregate
(3.01 → 3.78 ms at 9,000 rows under a 18,000 cap), which is the price every
small type pays for the large one. And a capped `total` is a number the UI
cannot page past; `next_cursor` (F11) is what walks beyond it.

The shape of the statement is the whole finding and is easy to get wrong in
two different ways, both of which produce a *wrong* answer rather than a slow
one:

```sql
-- after
SELECT count(anon_1.id) FROM (
    SELECT records_record.is_deleted, …, records_record.id, …
    FROM records_record
    WHERE records_record.type_id = ? AND records_record.is_deleted IS 0
    LIMIT 3001
) AS anon_1 WHERE anon_1.is_deleted IS 0
```

* The outer aggregate counts an `aliased(Record, subquery)`. The framework's
  soft-delete filter is attached per *mapper found in the statement*, so
  `select(func.count()).select_from(sub)` — which names none — counts the
  trash. Naming the entity through the alias puts `Record` back in the
  statement and the hook then renders its criteria **inside the subquery too**,
  which is where the `LIMIT` needs them: otherwise the bound fills with
  trashed rows the outer discards and `total` under-counts near the cap.
* The inner query selects *mapped attributes*, not `Record.__table__.c`. The
  Core columns compile to identical SQL and are not ORM entity references, so
  a statement selecting them names no mapper and the filter skips it —
  exactly the same wrong answer, arrived at from the other direction.
  `test_the_bound_does_not_fill_with_trashed_rows` catches both.

An earlier form, `count(Record.id) WHERE Record.id IN (limited)`, was correct
but read the matching rows twice: 6.7 ms against the plain count's 3.3 ms on
the same 9,000 rows.

### F5 — a sort on an indexed field materialised the whole type

`index/_sorting.py` replaces the `GROUP BY record_id` aggregate subquery with
a direct `LEFT OUTER JOIN` for a **single-valued** field. One record has at
most one row for such a field by construction, so nothing has to be
aggregated away; `MIN` survives only for `multiselect`, a to-many `relation`
and a provider's `many` virtual field, where a record really does hold
several values and one has to be chosen.

Fixed columns got a composite index each — `(type_id, <column>, id)` for
`position`, `published_at`, `updated_at`, `created_at`, `display_title` and
`slug`, in revision `fccc111ff2e9` — and the ordering stopped wearing
`NULLS LAST` on columns the database knows are `NOT NULL`.

| sort (9,000 orders unless noted) | before | after | |
|---|---|---|---|
| `placed_at` (datetime) | 31.00 ms | **21.45 ms** | |
| `-placed_at` | 32.27 ms | **21.52 ms** | |
| `customer` (relation, to-one) | 34.32 ms | **25.59 ms** | |
| `-customer` | 34.16 ms | **26.52 ms** | |
| `-published_at` (fixed, nullable) | 35.95 ms | **14.33 ms** | 2.5× |
| `position` (fixed, `NOT NULL`) | 14.73 ms | 14.05 ms | |
| `-position` | 14.57 ms | 14.11 ms | |
| `price` (number, 3,000 products) | 14.01 ms | 13.24 ms | |
| `tags` (multiselect, 3,000) | 18.05 ms | 20.35 ms | aggregate kept |
| `name` (text, 1,000 companies) | 10.96 ms | 12.13 ms | |

The plans are the finding; the milliseconds are what is left of it once the
per-request overhead (about 10 ms of FastAPI, contracts and serialisation) is
included.

```
  before: sort by placed_at / customer / tags  — all three identical
    MATERIALIZE anon_1
    SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=?)
    USE TEMP B-TREE FOR GROUP BY
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
    BLOOM FILTER ON anon_1 (record_id=?)
    SEARCH anon_1 USING AUTOMATIC COVERING INDEX (record_id=?) LEFT-JOIN
    USE TEMP B-TREE FOR ORDER BY
  after: sort by placed_at
    SEARCH records_record USING INDEX ix_records_record_type_created_id (type_id=?)
    SEARCH records_index_datetime_1 USING INDEX ix_records_index_datetime_record (record_id=?) LEFT-JOIN
    USE TEMP B-TREE FOR ORDER BY
  after: sort by customer (ref)
    SEARCH records_record USING INDEX ix_records_record_type_created_id (type_id=?)
    SEARCH records_index_ref_1 USING INDEX ix_records_index_ref_record (record_id=?) LEFT-JOIN
    USE TEMP B-TREE FOR ORDER BY
  after: sort by tags (multiselect) — unchanged, and correctly so
    MATERIALIZE anon_1 / TEMP B-TREE FOR GROUP BY / … / TEMP B-TREE FOR ORDER BY

  before: sort by position, and by -published_at
    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
    USE TEMP B-TREE FOR ORDER BY
  after: sort by position
    SEARCH records_record USING INDEX ix_records_record_type_position_id (type_id=?)
  after: sort by -published_at
    SEARCH records_record USING INDEX ix_records_record_type_published_id (type_id=?)
```

`MATERIALIZE` + `TEMP B-TREE FOR GROUP BY` + `AUTOMATIC COVERING INDEX` are
gone from every single-valued sort, and the fixed-column sorts have **no
sorter at all** — the index produces the order and the scan stops after
`page_size` rows.

Three things had to be right for that, and each was measured wrong first:

* **`type_id` is not in the join's `ON` clause.** A record belongs to one
  type, so the denormalised `type_id` on the index row adds nothing to the
  predicate — but given `type_id = ? AND field_key = ?` SQLite scores the
  two-equality `(type_id, field_key, value)` lookup index above the
  single-equality `(record_id)` one, and then re-scans the whole (type, field)
  range once per record of the type. Sorting 9,000 orders by `customer` took
  **42 seconds** that way. §7.3's "denormalised so a query never joins to
  filter by type" is about the *filter* semi-join, which still uses all three.
* **`NULLS LAST` comes off only where the column cannot be null.** It is not
  the order a btree stores, so a fixed-column sort wearing it is answered with
  a temp B-tree over the whole type even when a composite index covers the
  column exactly. `NOT_NULL_FIXED_COLUMNS` is read off the mapper rather than
  listed, because getting it wrong in that direction reorders a page.
* **The `Record.id` tiebreaker reverses only for a sort one index can serve
  end to end** — a single descending term on a column with a
  `(type_id, col, id)` index. There, `… DESC, id ASC` cannot be read off the
  index in either direction, so SQLite walks it backwards and re-sorts every
  group of equal values; on the common degenerate case (a type nobody has
  hand-ordered, so every `position` is `0`) that is one group holding the whole
  type. Everywhere else the reverse tiebreaker is a **disaster**, and it was
  measured as one: rows reach the sorter in `id` order, so an ascending
  tiebreaker lets every row past the first `page_size` be discarded on one
  comparison, while a descending one makes every row better than the current
  worst — 9,000 insert-and-evict cycles copying whole records, payload
  included. On the list's default `(position, -updated_at)` ordering that is
  **4.1 ms with `id ASC` against 25.8 ms with `id DESC`**, same plan line,
  same rows.

**What the six indexes cost.** Writes did not measurably change
(`create_record` 11.00 → 10.07 ms, 13 statements either way; the
delete/restore/purge cycle 40.62 → 36.15 ms) — six more btree inserts are
lost in the round trips a write already makes. What did change is the admin
list view's **default two-term ordering**, `position ASC, updated_at DESC`:
SQLite now prefers to read `ix_records_record_type_position_id` for the first
term and re-sort each group for the second, which on this dataset — every
`position` is `0`, so there is one group — costs 4.1 ms against 7.0 ms for the
plain scan it replaced. `ANALYZE` does not change that choice. It is a real
1.7× on that one query, it is the reason `GET /admin/records/order` reads
30.05 → 37.61 ms below, and it inverts on a type whose `position` values are
actually distinct, where the same plan stops after 25 rows. An install that
never hand-orders anything can drop
`ix_records_record_type_position_id` and lose only `?sort=position`.

### F9 — the relation picker searched a column no index could serve

`components/RelationPicker.tsx` sent `display_title:contains:<term>` on every
keystroke after the debounce — `ILIKE '%term%'` over `records_record`, which
reads every row of the target type by construction. It now asks
`display_title:starts_with:<term>` first and falls back to `contains` only
when the prefix returned fewer than five rows, merging the two without
duplicates (`utils/relation-search.ts`).

| picker query, 5,000 contacts | before | after |
|---|---|---|
| `display_title:contains:Smith` | 6.75 ms | — |
| `display_title:starts_with:Smith` | — | **5.29 ms** |

```
  contains:    SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
  starts_with: SEARCH records_record USING INDEX ix_records_record_type_title_id
                 (type_id=? AND display_title>? AND display_title<?)
```

The milliseconds are the smaller half of it — at 5,000 contacts the request's
own overhead dominates either way. The plan is the finding: `contains` reads
the type and `starts_with` seeks a range, so one grows with the type and the
other with what matches.

**`starts_with` is a range, not a `LIKE`.** `LIKE 'term%'` expresses the same
set and cannot be answered from these indexes: SQLite's LIKE optimisation
needs a `NOCASE`-collated index while `case_sensitive_like` is off (the
default), and Postgres needs `text_pattern_ops` under any non-C collation.
`_predicates.prefix_range` produces `term <= value < successor(term)` instead,
stepping over the surrogate block and returning no upper bound for a term of
maximum code points. The cost is that `starts_with` is case- and
collation-sensitive where `contains` is neither — which is why the picker asks
in that order and why both operators exist.

### F10 — `POST /schema/preview` was synchronous

The dry run validates every record of the type, trash included, at roughly a
thousand records a second. It stays inside the request up to
`RecordsSettings.preview_sync_limit` (new, default 5,000) and answers
`202 {"job": …, "status": "running"}` above it, running the scan through the
module's own deferred-job mechanism on its own session
(`services/preview_jobs.py`, `endpoints/api/preview.py`).
`GET /types/{key}/schema/preview/{job}` returns `{status, checked, total,
preview}`, the scan reporting `checked` per batch, and the type editor polls
it once a second and shows "Checked N of M…".

| `POST /schema/preview`, `order.gift` becomes required, 9,000 records | before | after |
|---|---|---|
| time until the caller has a response | 1312.74 ms | **4.98 ms** (`202`) |
| time until the report exists | 1313.71 ms | 1335.52 ms |

The second row is the point of the first: the scan costs what it always cost
(`dry_run` itself is 8029 → 8023 ms under `tracemalloc`, unchanged), and what
moved is when the caller is answered. Measuring this needs an ASGI wrapper
outside the whole middleware stack (`tests/perf/test_preview_job.py`) —
`DeferredJobsMiddleware` drains the job after the response is sent but before
the ASGI call returns, so an HTTP client timing the round trip sees the two
paths take the same time and learns nothing.

**Saving after a preview no longer scans twice.** `PUT /types/{key}` reuses a
completed job's report when it was taken against the same type, the same
proposed fields and the same `RecordType.version` — the value the caller
already had to send as `expected_version` and which `apply` has already
checked under the type's row lock, so the schema the report describes is
provably the schema being changed. What the version does not cover is records
written in between, which is what `preview_job_ttl_seconds` (new, default 600)
bounds; `0` turns every save back into its own inline pass, and an
`orphaned="discard"` save always runs one because no preview judged the
records without the values being discarded. §8.9's rule that no report is ever
*persisted* is untouched: the registry is in-process, bounded to 50 entries,
pruned by age, and a `404` from the poll simply means "preview again".

### F11 — `OFFSET` pagination

`?after=<cursor>` pages by keyset. The cursor is an opaque base64 of the row's
sort values and its id, carrying a digest of the sort it was produced under;
a cursor that does not decode, one replayed under a different sort or against
the trash, and `?page=` and `?after=` sent together are each a `400`. `?page=`
stays for the admin UI, which shows numbered pages.

| page 200 of 9,000 orders, `sort=-placed_at` | before | after |
|---|---|---|
| `?page=200` (`OFFSET 4975`) | 62.22 ms, 3 statements | — |
| `?after=<cursor>&total=false` | — | **18.38 ms, 2 statements** |

Both plans are identical — the same index, the same join, the same temp
B-tree — and the difference is entirely the 4,975 rows `OFFSET` produces and
throws away. The two return byte-identical pages, which the measurement
asserts.

The keyset predicate is written out rather than expressed as a row-value
comparison (`(a, b) > (?, ?)`): a row comparison cannot express per-term
directions, cannot express `NULLS LAST`, and is not available on every backend
this module claims to run on. `NULL` sorts last, so nothing is after it —
`false()` rather than a comparison, because a comparison against SQL `NULL` is
unknown and would silently drop every remaining row instead of ending the
walk. Cursor values decode with `datetime.fromisoformat` and friends rather
than with the filter grammar's coercers: a filter value was typed by a human
and is validated (`coerce_datetime` refuses a naive timestamp), while a cursor
value came out of the column on the previous page and has to go back in
unchanged — SQLite hands back a naive `datetime` for a `DateTime(timezone=True)`
column, and coercing it the filter way turned every `?after=` over a datetime
sort into a 400.

### What the list page costs now that it does all this

| | before | after |
|---|---|---|
| `GET /order/records` page 1, 9,000 records | 11.56 ms | 14.04 ms |
| `GET /admin/records/order` (Inertia, 8 statements) | 30.05 ms | 37.61 ms |

About 1 ms of that is the page itself — the sort values are now selected
alongside the record and a cursor is encoded for the last row — and the rest
is the two costs named above: the bounded count on a type below the ceiling
(+0.8 ms) and the default two-term ordering's new plan (+2.9 ms). A caller
that sends `?total=false` is at **8.53 ms**, below where the page started.

## Still open

Nothing from the study. Two costs above are deliberate trades rather than
open findings, and both are written down where the code makes them:
`ix_records_record_type_position_id` slowing the default two-term list
ordering on a type whose `position` is uniform (F5), and the bounded count
costing an extra aggregate on a type below `max_count` (F4).

## Reference numbers after the fixes

`RECORDS_PERF_N=20000`, p50 over 20 repetitions, through
`GET /api/records/…`. A list page is **3 SQL statements** regardless of page
size or table size, and **2** with `?total=false` or `?after=`; a single
record GET is 2; the Inertia list view is 8 (§9's batched expansion, one query
per relation field).

| operation | type size | p50 ms |
|---|---|---|
| list page 1, unfiltered | 9,000 | 14.0 |
| the same with `?total=false` (2 statements) | 9,000 | 8.5 |
| list page 200 by `?page=` (`OFFSET 4975`, sorted) | 9,000 | 62.2 |
| list page 200 by `?after=` | 9,000 | 18.4 |
| single record by uuid | 9,000 | 4.1 |
| text `eq` / `contains` | 1,000 | 7.1 / 12.0 |
| `display_title` `starts_with` / `contains` | 5,000 | 5.3 / 6.8 |
| select `eq` | 9,000 | 11.1 |
| multiselect `eq` | 3,000 | 11.1 |
| ref `eq` | 9,000 | 7.5 |
| number / date / datetime / bool range | 1,000–9,000 | 11.6–21.6 |
| three ANDed filters | 9,000 | 42.6 |
| `in` with 50 values | 5,000 | 27.1 |
| sort by an indexed single-valued field | 1,000 / 3,000 / 9,000 | 12.1 / 13.2 / 21.5–26.5 |
| sort by a multiselect (the `MIN` aggregate) | 3,000 | 19.6–20.4 |
| sort by a fixed column | 9,000 | 13.7–14.5 |
| the count alone, for one filtered page | 9,000 | 1.1 |
| the count alone, unfiltered, bounded / unbounded | 9,000 | 1.8 / 3.0 |
| Inertia `/admin/records/order` | 9,000 | 37.6 |
| `create_record` (13 statements, 14 with a unique field) | 20,000 total | 10.1–11.0 |
| `update_record` (20/21 statements) | 20,000 total | 14.1–14.7 |
| trash → restore → trash → purge (46 statements) | 20,000 total | 36.2 |
| `run_pending` rebuild, 2,000 records | | 404–603 ms (3,300–5,000 rec/s) |
| `POST /schema/preview`, 9,000 records, as a `202` | | 5.0 ms, job done in 1.3 s |
| `POST /schema/preview` dry run under `tracemalloc` | 9,000 | 8.0 s, peak 4.3 MB |
| `_orphaned.count_conflicts` / `.discard` | 2,000 | 45 ms / 140 ms |
| type revision rollback | — | 10.7 ms |

## What is already fine

* Statement counts are constant in rows returned and in table size.
* The Phase 3 list-page validation cost is gone — `record_list_read` computes
  `field_defs` once and skips the per-row `invalid` pass.
* `count_query`'s `func.count(Record.id)` (rather than a bare `count()`) is
  what attaches the soft-delete filter; `exists_query` names the mapper for the
  same reason, and `bounded_count_query` goes to some length to keep a mapper
  in a statement whose natural spelling has none. Do not "simplify" any of the
  three — F4 above says what each wrong spelling returns.
* The batched schema passes are memory-safe: 4.3 MB peak over 9,000 records.
* The keyset paging in `reindex_type`, `_dry_run._batches` and
  `_orphaned._records` is correct and shows clean index use.
* Pydantic validation (0.4% of a create) and the relation target check
  (0.006 ms) are not worth optimising.

## On Postgres

Untested here — no Postgres binary was available. Expectations:

* The **statement counts** are a property of the code and identical on any
  backend, so F2, F6, F7 and F8 land there too, and the round-trip ones
  (F6's six deletes, F7's second `records_type` read, F8's per-record writes)
  are worth *more* there than on an in-process SQLite file.
* The **semi-join should still win**, because it is proportional to matches
  rather than to the size of the type. The pathological ratios above are
  SQLite-with-no-statistics and should not reproduce under autovacuum — except
  immediately after a restore or a bulk load, which is exactly the state a
  migration leaves.
* `analyze_tables` is a **no-op on Postgres** by design (`dialect.name !=
  "sqlite"`): autovacuum owns those statistics.
* The **sort joins and the fixed-column indexes** are ordinary btree work and
  should behave at least as well there, but the two planner choices F5
  documents are SQLite's own: the `type_id`-in-the-`ON`-clause trap came from
  SQLite scoring equality columns with no statistics, and the default
  two-term ordering's regression from it preferring a partial index order.
  Postgres with live statistics should make neither choice — verify rather
  than assume, by reading `EXPLAIN` for a sort on an indexed field and for
  `ORDER BY position, updated_at DESC`.
* **`starts_with` is collation-sensitive on Postgres** in a way it is not on
  SQLite: the range `term <= value < successor` means what the column's
  collation says it means. A picker that must be case-insensitive there wants
  a `lower(display_title)` expression index and an operator over it, which is
  not what this one is.
* **`lock_type` keeps `FOR UPDATE` there**, which is a real row lock, so the
  F3 race should already be closed. Verify rather than assume: run
  `tests/test_unique_concurrency.py` against Postgres and count the 201s.
