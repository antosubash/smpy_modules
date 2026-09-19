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
`RECORDS_PERF_DB` points it at a database seeded elsewhere. It prints a results
table and the `EXPLAIN QUERY PLAN` of each operation's heaviest statement, and
asserts only shapes — "a filtered list does not full-scan `records_record`",
"a create issues no index `DELETE`s", "a page costs a constant number of
statements" — never wall-clock thresholds.

## Fixed

Six of the eleven findings. Each row is p50 over 20 repetitions on the same
seeded file, before → after.

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

## Still open

Five findings from the study, untouched. Numbers are from the same pair of
runs, so they are measured *after* the six fixes above — the semi-join makes
several of them cheaper in absolute terms without changing their shape.

* **F4 — every list page computes an unbounded total.** `services/records.py`,
  `list_records`. The page can stop after 25 matches; the count never can.
  Now 1.04 ms of a 9.55 ms filtered request at 20,000 (it was 11.05 ms of
  26.64 ms), so the semi-join took the sting out without removing the
  property: it is still O(matches) rather than O(page), and a filter matching
  most of a large type still pays for all of it. The fix is a product decision
  (`?total=false`, or a capped `10000+`), not a patch.
* **F5 — a sort on an indexed field materialises the whole type.**
  `index/query._sorted` builds a `GROUP BY record_id` aggregate subquery and
  outer-joins it: `MATERIALIZE` + `TEMP B-TREE FOR GROUP BY` +
  `AUTOMATIC COVERING INDEX` + `TEMP B-TREE FOR ORDER BY`. Cost scales with
  the type, not the page: sorting 9,000 orders by `placed_at` is 29.25 ms
  (was 30.37) and by `customer` 32.71 ms (was 35.06), for 25 rows. The
  `GROUP BY` is only needed for `multiselect` and to-many `relation`. Even a
  **fixed-column** sort builds a temp B-tree (13.46 ms) although
  `ix_records_record_type_status_position` exists — that one is `nulls_last`
  plus the `Record.id` tiebreaker not matching the index.
* **F9 — the relation picker searches a column no index can serve.**
  `components/RelationPicker.tsx` sends
  `filter=display_title:contains:<term>`, which is `ILIKE '%term%'` on
  `records_record`: 10.10 ms over 5,000 contacts (was 10.78), growing linearly
  with the type, on every keystroke after the debounce. A `starts_with`
  operator over the *indexed* text column would be index-backed, and is a
  product decision about what the picker finds.
* **F10 — `POST /schema/preview` is synchronous.** `dry_run(order, gift
  required)` over 9,000 orders is 7,718 ms (was 7,839) at 1,166 rec/s, so
  ~40 s at 45,000 — a real HTTP request, with whatever proxy timeout that
  implies. `tracemalloc` peak 4.3 MB, so the batching is fine and memory is
  not the issue.
* **F11 — `OFFSET` pagination.** Page 1 of 9,000 orders is 11.08 ms, page 200
  (`OFFSET 4975`) is 13.00 ms. Mild, and linear in the rows skipped. Three
  *internal* walks (`reindex_type`, `_dry_run._batches`, `_orphaned._records`)
  already use keyset paging and say why; the user-facing list is the one place
  that does not.

## Reference numbers after the fixes

`RECORDS_PERF_N=20000`, p50 over 20 repetitions, through
`GET /api/records/…`. Every list operation is **3 SQL statements** regardless
of page size or table size; a single record GET is 2; the Inertia list view
is 5.

| operation | type size | p50 ms |
|---|---|---|
| list page 1, unfiltered | 9,000 | 11.1 |
| list page 200 (`OFFSET 4975`) | 9,000 | 13.0 |
| single record by uuid | 9,000 | 3.7 |
| text `eq` / `contains` | 1,000 | 5.6 / 10.1 |
| select `eq` | 9,000 | 9.6 |
| multiselect `eq` | 3,000 | 9.5 |
| ref `eq` | 9,000 | 5.7 |
| number / date / datetime / bool range | 1,000–9,000 | 9.8–18.9 |
| three ANDed filters | 9,000 | 40.3 |
| `in` with 50 values | 5,000 | 23.9 |
| sort by an indexed field | 1,000 / 3,000 / 9,000 | 10.8 / 12.4–13.4 / 29.3–33.2 |
| sort by a fixed column | 9,000 | 13.5–14.2 |
| the count alone, for one filtered page | 9,000 | 1.0 |
| Inertia `/admin/records/order` | 9,000 | 19.6 |
| `create_record` (13 statements, 14 with a unique field) | 20,000 total | 10.7–10.9 |
| `update_record` (20/21 statements) | 20,000 total | 14.3–15.0 |
| trash → restore → trash → purge (46 statements) | 20,000 total | 37.0 |
| `run_pending` rebuild, 2,000 records | | 448–611 ms (3,275–4,463 rec/s) |
| `POST /schema/preview` dry run, 9,000 records | | 7.7 s, `tracemalloc` peak 4.3 MB |
| `_orphaned.count_conflicts` / `.discard` | 2,000 | 42 ms / 134 ms |
| type revision rollback | — | 11 ms |

## What is already fine

* Statement counts are constant in rows returned and in table size.
* The Phase 3 list-page validation cost is gone — `record_list_read` computes
  `field_defs` once and skips the per-row `invalid` pass.
* `count_query`'s `func.count(Record.id)` (rather than a bare `count()`) is
  what attaches the soft-delete filter; `exists_query` names the mapper for the
  same reason. Do not "simplify" either.
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
* **`lock_type` keeps `FOR UPDATE` there**, which is a real row lock, so the
  F3 race should already be closed. Verify rather than assume: run
  `tests/test_unique_concurrency.py` against Postgres and count the 201s.
