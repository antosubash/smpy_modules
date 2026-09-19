> **Point-in-time record.** The full performance study as delivered on 2026-09-19, measured against a pinned snapshot of commit `b13b362` on SQLite 3.45.1 (no Postgres in the environment). `performance.md` beside this file is the maintained summary; this document is the evidence. `<scratchpad>` paths refer to a scratch directory that was not kept; the durable suite is `tests/perf/`.

# Records module — performance study

**Measured revision:** `b13b362` (`records: API QA fixes — reserved keys,
relations always indexed, roles on delete`), `modules/records/sm_records`
clean against HEAD at the time of every run below.

## 0. Headline

* **A filtered list page can take seven minutes.** `filter=placed_at:gte:…`
  over 45,000 orders: p50 **442,735 ms**. Three ANDed filters: 410,668 ms.
  A boolean filter over 15,000 products: 14,324 ms.
* **One `ANALYZE`, costing 0.2 s, fixes that: 442,735 ms → 52.59 ms (8,418×).**
  It is a SQLite planner-statistics problem, and nothing in the module or its
  migrations ever runs `ANALYZE`.
* **Writes to a type with a `unique` field are O(rows in that type).** The
  uniqueness check is an unbounded `COUNT` over every record of the type:
  50.4% of a create at 15,000 rows, 9.0% at 1,000. The module's own seeder
  could not reach 100,000 records because of it — 31,400 in 22 minutes, with
  the rate falling from 72 rec/s to 14 rec/s.
* **`unique` is not enforced under concurrency.** Eight simultaneous creates
  with the same `contact.email` all returned 201 and all eight rows were
  stored. (`SELECT … FOR UPDATE` is a no-op on SQLite; unverified on Postgres.)
* **Everything structural is sound.** Statement counts are constant — 3 per
  list page, 20 per create — nothing is O(rows), the index tables carry the
  right composite indexes, the batched schema passes hold 4.4 MB at 45,000
  records, and the Phase 3 list-page validation cost is gone.

## 1. Environment and caveats

| | |
|---|---|
| Backend | **SQLite 3.45.1 only** — this container has no Postgres binary, and none was installed |
| Driver / ORM | aiosqlite 0.22.1, SQLAlchemy 2.0.51, `journal_mode=delete` (SQLAlchemy's default; no WAL) |
| Python | 3.12, `/home/user/smpy_modules/.venv/bin/python` |
| Host | 4 cores, 15 GB RAM, single process, no other load except where noted |
| Storage | file-backed SQLite under the session scratchpad (never `:memory:`), so every number includes real page I/O |
| HTTP | in-process ASGI through `httpx.ASGITransport` and `tests/app_harness.py`, so the endpoint code, its dependencies and Pydantic serialisation are all in the measurement; no network, no uvicorn |
| Statistics | p50 / p95 over 20 timed repetitions after 3 untimed warm-ups, unless a row says otherwise |

**Caveats that change how to read every number below.**

* **SQLite is not the deployment target, and three of the findings are
  backend-independent while two are not.** Wherever a finding is a property
  of the SQL the module emits (a correlated `EXISTS`, an `OFFSET` walk, a
  statement count) it is stated as such and will reproduce on Postgres.
  Wherever it is SQLite's single-writer lock or its lack of `SELECT … FOR
  UPDATE`, it is labelled *SQLite-only*. §8 lists what could not be measured
  here at all.
* **No `ANALYZE` was run.** A real install does not run one either — nothing
  in the module or its migrations does — so the plans below are the plans a
  deployed SQLite install gets.
* **The module was under active edit by another agent during this study.**
  The seeder's `order.status` field was renamed to `order_status` mid-run
  (it collided with the newly-added reserved-field-key rule), and
  `tests/app_harness.py` — which this study extended with an optional
  `db_state` argument — was swept into commit `b13b362` by that agent, not
  by this study. All numbers below were taken against the code as of that
  commit.
## 2. Dataset

Five demo Record Types from `sm_records.seed.types` — `company`, `contact`,
`product`, `store`, `order` — with the relations and unique fields the seeder
declares (`contact.email`, `product.sku`, `order.order_no` unique;
`contact.company`, `store.manager`, `order.customer`, `order.products`
relations).

| type | records | unique field | relations |
|---|---|---|---|
| `order` | 45,000 | `order_no` | `customer` → contact, `products` → product (to-many) |
| `contact` | 25,000 | `email` | `company` → company |
| `product` | 15,000 | `sku` | — |
| `store` | 10,000 | — | `manager` → contact |
| `company` | 5,000 | — | — |
| **total** | **100,000** | | |

Index rows written: `records_index_text` 322,367 · `records_index_ref`
214,520 · `records_index_number` 80,000 · `records_index_datetime` 45,000 ·
`records_index_bool` 45,000 · `records_index_date` 40,000 —
**747,887 index rows** for 100,000 documents, plus 100,000 `records_revision`
rows. The database file is 204 MB.

### How the dataset was built, and why it is not the seeder's output

**The seeder could not reach 100,000 records, and that is finding #1, not a
tooling problem.** `python -m sm_records.cli seed --records 100000` was
started first and left running for 22 minutes. It wrote **31,400 records** in
that time and was still inside the `contact` type:

```
records seed: 31400/100000 records written     # after 22 min; company 5000, contact 25000, product 1400, store 0, order 0
```

Sampled progress (wall-clock offsets from process start):

| elapsed | records written | rate over the preceding interval |
|---|---|---|
| 25 s | 1,800 | 72 /s |
| 300 s | 11,000 | ~33 /s |
| 640 s | 21,000 | 29 /s |
| 1,018 s | 27,200 | 16 /s |
| 1,310 s | 31,400 | 14 /s |

The rate falls monotonically with the number of rows already in the type
being written. §5 shows why. The run was stopped at 31,400 rather than left
to finish, because the remaining 45,000 `order` records — a type with a
unique field — would have taken hours on that curve.

The 100,000-record dataset used for every **read-path** and **schema-op**
measurement was therefore built by
`scratchpad/perf/bulk_load.py`, which keeps everything the read path can
observe and drops only the per-write round trips:

* every payload goes through the type's compiled validator
  (`_payload.validate`), so `data` is exactly what the service would store;
* `display_title` and `slug` come from `_payload.display_title` /
  `_payload.slug_for`;
* **every index row is projected by the real index provider**
  (`index.providers.providers()` + `index.writer._row`), so the index tables
  are bit-for-bit what `write_index` would have written;
* one `records_revision` row per record, as `create_record` writes;
* the uniqueness `SELECT`, the type lock, the slug check and the per-record
  flush are replaced by batched bulk inserts.

It loaded 100,000 records in **83.1 s (1,204 rec/s)** — 50× the seeder — and
the gap between those two numbers is the subject of §5.

Write-path numbers in §5 come from the **real** `create_record`, never from
the bulk loader.
## 3. How to reproduce

The durable half of this study is a pytest suite in the module:

```
modules/records/tests/perf/
├── _bench.py        # perf_counter timing, p50/p95, before_cursor_execute statement counter,
│                    # EXPLAIN QUERY PLAN capture, the results table
├── _http.py         # drive the real endpoints, label a plan
├── conftest.py      # the seeded file-backed database, the app wired to it
├── test_write_path.py
├── test_read_path.py
└── test_schema_ops.py
```

Marked `perf` and excluded from the default run by
`addopts = "-m 'not perf'"` in `modules/records/pyproject.toml` (and in the
repo root's, since root `testpaths` includes `modules/records/tests`):

```
cd modules/records && uv run pytest              # 401 passed, 22 deselected
cd modules/records && uv run pytest -m perf tests/perf     # the perf suite
```

Size and repetitions are environment variables — `RECORDS_PERF_N` (default
**2000**, ~1 minute end to end), `RECORDS_PERF_REPS` (default 20) and
`RECORDS_PERF_DB` (point it at a database seeded elsewhere). The suite
asserts only shapes that are properties of the code — "a filtered list does
not full-scan `records_record`", "one page costs a constant number of
statements" — never a wall-clock threshold, which would flake.

The exact commands behind every number below:

```sh
PERF=<scratchpad>/perf
# the dataset
python "$PERF/bulk_load.py" "$PERF/n100k.db" 100000 42
# the suite, at 100k, 20 reps
cd modules/records && RECORDS_PERF_DB=$PERF/n100k.db RECORDS_PERF_N=100000 \
  RECORDS_PERF_REPS=20 python -m pytest -q -m perf tests/perf -s
# write throughput against table size, through the real create_record
python "$PERF/scale_write.py" "$PERF/scale.db" 40000 "1000,5000,10000,20000"
# where a create's time goes
python "$PERF/profile_create.py" "$PERF/prof100k.db" product 50
# correlated EXISTS vs a semi-join from the index
python "$PERF/altquery.py" "$PERF/n100k.db" 20
# 8 concurrent writers, and the unique race
python "$PERF/concurrency.py" "$PERF/conc100k.db" 8 25
# the seeder, for comparison
python -m sm_records.cli seed --records 100000 --database-url sqlite+aiosqlite:///$PERF/big.db
```

## 4. Results

All at the 100,000-record dataset. `stmts` is SQL statements per operation
(`before_cursor_execute`); `plan` names the indexes SQLite's
`EXPLAIN QUERY PLAN` reported for the heaviest statement. `reps` is how many
timed samples fit in the per-measurement budget — a row with `reps 1` is one
sample because one call took minutes.

Command: `RECORDS_PERF_DB=$PERF/n100k.db RECORDS_PERF_N=100000 RECORDS_PERF_REPS=20
RECORDS_PERF_BUDGET=10 pytest -q -m perf tests/perf -s` (52 min, full output in
`study_suite.txt`).

### 4.1 Read path, through `GET /api/records/...`

| operation | N (type) | p50 ms | p95 ms | reps | stmts | plan uses index? |
|---|---|---|---|---|---|---|
| list page 1, unfiltered (order) | 45,000 | **23.52** | 24.17 | 20 | 3 | `ix_records_record_type_id` |
| list page 200, unfiltered (order) | 45,000 | 26.55 | 35.03 | 20 | 3 | `ix_records_record_type_id` |
| text `eq` (company.city) | 5,000 | 17.54 | 19.21 | 20 | 3 | `ix_records_index_text_record` (by `record_id`) |
| text `contains` (company.name) | 5,000 | 17.29 | 18.02 | 20 | 3 | `ix_records_index_text_record` |
| `contains` spanning `value`/`value_full` | 5,000 | 21.03 | 21.77 | 20 | 3 | `ix_records_index_text_record` |
| select `eq` (order.ship_state) | 45,000 | 71.23 | 72.80 | 20 | 3 | `ix_records_index_text_record` |
| multiselect `eq` (product.tags) | 15,000 | 36.10 | 37.43 | 20 | 3 | `ix_records_index_text_record` |
| ref `eq` (order.customer) | 45,000 | 136.42 | 139.93 | 20 | 3 | `ix_records_index_ref_lookup` |
| `in` with 50 values (contact.email) | 25,000 | 72.76 | 76.26 | 20 | 3 | `ix_records_index_text_record` |
| fixed-column `eq` (status) | 45,000 | 27.27 | 34.43 | 20 | 3 | `ix_records_record_type_id` |
| relation-picker search (`display_title contains`) | 25,000 | 20.93 | 22.08 | 20 | 3 | `ix_records_record_type_id`, then ILIKE per row |
| **number range `gte` (product.price)** | 15,000 | **39,978** | 39,978 | 1 | 3 | `ix_records_index_number_lookup` — *value range, per outer row* |
| **bool `eq` (product.in_stock)** | 15,000 | **14,324** | 14,324 | 1 | 3 | `ix_records_index_bool_lookup` — *ditto* |
| **date range `gte` (company.founded)** | 5,000 | **3,386** | 3,502 | 3 | 3 | `ix_records_index_date_lookup` — *ditto* |
| **datetime range `gte` (order.placed_at)** | 45,000 | **442,735** | 442,735 | 1 | 3 | `ix_records_index_datetime_lookup` — *ditto* |
| **3-filter AND (number + select + datetime)** | 45,000 | **410,668** | 410,668 | 1 | 3 | three correlated subqueries, two of them ranges |
| sort by text, asc / desc (company.name) | 5,000 | 21.49 / 21.47 | 25.06 / 22.93 | 20 | 3 | `ix_..._text_lookup` + MATERIALIZE + 2 temp B-trees |
| sort by number, asc / desc (product.price) | 15,000 | 40.24 / 38.76 | 43.22 / 41.57 | 20 | 3 | same shape |
| sort by bool, asc / desc | 15,000 | 33.97 / 32.82 | 35.86 / 33.72 | 20 | 3 | same shape |
| sort by date, asc / desc | 5,000 | 19.25 / 19.44 | 20.27 / 20.72 | 20 | 3 | same shape |
| sort by datetime, asc / desc (order) | 45,000 | 134.86 / 137.48 | 137.55 / 140.82 | 20 | 3 | same shape |
| sort by ref, asc / desc (order.customer) | 45,000 | 170.04 / 172.45 | 178.34 / 178.53 | 20 | 3 | same shape |
| sort by fixed column (updated_at) | 45,000 | 44.14 / 39.95 | 45.91 / 43.47 | 20 | 3 | `ix_records_record_type_id` + TEMP B-TREE |
| `count_query` alone (order, ship_state) | 45,000 | 59.55 | 60.90 | 20 | 1 | `ix_records_index_text_record` |
| single record GET by uuid | 45,000 | **3.78** | 4.10 | 20 | 2 | `ix_records_record_uuid` |
| Inertia list view `/admin/records/order` | 45,000 | 60.28 | 66.60 | 20 | 5 | `ix_records_record_type_id` + TEMP B-TREE |

### 4.2 The same read path after one `ANALYZE`

`ANALYZE` on the 204 MB database took **0.2 s**. Nothing else changed — same
code, same data, same queries. Command:
`RECORDS_PERF_DB=$PERF/analyze.db … pytest -q -m perf tests/perf/test_read_path.py -s`
(full output in `study_suite_analyzed.txt`).

| operation | before, p50 ms | after, p50 ms | change | plan after |
|---|---|---|---|---|
| datetime range `gte` (order, 45k) | 442,735 | **52.59** | **8,418×** | `ix_records_index_datetime_record` (by `record_id`) |
| 3-filter AND (order, 45k) | 410,668 | **101.52** | **4,045×** | `…_datetime_record`, `…_number_record` |
| number range `gte` (product, 15k) | 39,978 | **21.11** | **1,894×** | `ix_records_index_number_record` |
| bool `eq` (product, 15k) | 14,324 | **20.68** | **693×** | `ix_records_index_bool_record` |
| date range `gte` (company, 5k) | 3,386 | **13.17** | **257×** | `ix_records_index_date_record` |
| everything else | — | within ±15% | — | unchanged |

The plans say exactly what happened: without statistics SQLite picks
`(type_id, field_key, value)` inside the correlated subquery, which satisfies
the *value* predicate and leaves `record_id = records_record.id` as a filter
over the whole matching range. With statistics it picks
`(record_id)` instead, which satisfies the correlation in one probe.

### 4.3 Write path

| operation | rows in the type | p50 ms | p95 ms | reps | stmts | rec/s |
|---|---|---|---|---|---|---|
| `create_record(company)` — no `unique` field | 5,000 | **14.36** | 14.78 | 20 | 20 | 70 |
| `create_record(product)` — `unique` sku | 15,000 | **36.21** | 38.04 | 20 | 21 | 28 |
| `update_record`, no indexed field changed | 15,000 | 35.60 | 36.24 | 20 | 21 | 28 |
| `update_record`, indexed `price` changed | 15,000 | 36.16 | 37.57 | 20 | 22 | 28 |
| trash → restore → trash → purge, one record | 5,000 | 40.29 | 42.50 | 10 | 53 | — |

The statement count per create is **constant at 20** (asserted by
`test_create_statement_count_is_flat`), and updating an indexed field costs
the same as not updating it — `write_index` rewrites a record's whole row set
either way.

**`create_record` against table size** (`scale_write.py`, real service, 20
timed creates per checkpoint). `product` has a unique `sku`; `company` does
not; both have six indexed fields.

| rows in the type | `create(product)` | rec/s | `create(company)` | rec/s |
|---|---|---|---|---|
| 1,000 | 13.24 ms | 75.5 | 10.86 ms | 92.1 |
| 5,000 | 18.81 ms | 53.2 | 11.06 ms | 90.4 |
| 10,000 | 26.91 ms | 37.2 | 10.22 ms | 97.8 |
| 20,000 | 42.37 ms | 23.6 | 12.46 ms | 80.2 |

The `company` column is flat; the `product` column grows at ~1.5 µs per
existing row.

**Where a create's time goes** (`profile_create.py`, phase timers around the
service's own internals, 30 creates):

| phase | at 15,000 rows | % | at ~1,000 rows | % |
|---|---|---|---|---|
| `ensure_unique` (index COUNT) | **20.620 ms** | **50.4%** | 1.979 ms | 9.0% |
| index rows (6 DELETE + N INSERT) | 11.137 ms | 27.2% | **10.944 ms** | **49.6%** |
| revision insert + trim | 2.298 ms | 5.6% | 2.283 ms | 10.4% |
| `lock_type` (`SELECT … FOR UPDATE`) | 1.088 ms | 2.7% | 1.152 ms | 5.2% |
| `ensure_slug_free` | 1.079 ms | 2.6% | 1.329 ms | 6.0% |
| `type_id_map` (×2 per write) | 0.955 ms | 2.3% | 0.859 ms | 3.9% |
| `field_defs` (re-validate the schema) | 0.588 ms | 1.4% | 0.677 ms | 3.1% |
| `validate` (Pydantic) | 0.158 ms | 0.4% | 0.163 ms | 0.7% |
| relation target check | 0.006 ms | 0.0% | 0.007 ms | 0.0% |
| ORM insert / flush / overhead | 2.998 ms | 7.3% | 2.651 ms | 12.0% |
| **total** | **40.93 ms** | | **22.05 ms** | |

### 4.4 Schema operations at 100k

| operation | records touched | wall time | throughput | memory peak |
|---|---|---|---|---|
| `dry_run(order, gift required)` — cold cache | 45,000 | **40.6 s** | 1,107 rec/s | **4.4 MB** (`tracemalloc`) |
| `schema_change.apply(force=True)` — same change, warm cache | 45,000 | 6.7 s | 6,710 rec/s | — |
| toggle `indexed`, `run_pending`, `reindex_batch_size=100` | 10,000 | 76.3 s | **131 rec/s** | — |
| … `reindex_batch_size=500` (the default) | 10,000 | 74.9 s | **134 rec/s** | — |
| … `reindex_batch_size=2000` | 10,000 | 92.7 s | **108 rec/s** | — |
| `display_field` change → whole-type rebuild | 10,000 | 76.3 s | 131 rec/s | — |
| `_orphaned.count_conflicts` | 10,000 | 257 ms | 39,000 rec/s | — |
| `_orphaned.discard` (the one bulk payload write) | 10,000 | 869 ms | 11,500 rec/s | — |
| type revision rollback (no field change) | — | 12 ms | — | — |

Batch size is nearly irrelevant to the rebuild and 2000 is *worse* than 500 —
the cost is per record, not per batch.

### 4.5 Concurrency

`concurrency.py`, 8 asyncio writers against the 100k dataset through the
in-process HTTP client.

```
=== 8 concurrent writers x 25 creates ===
succeeded: 200/200 in 7.71s (26.0 creates/s aggregate)
```

No `database is locked` errors; aggregate throughput (26.0/s) is slightly
*below* single-writer throughput for the same type (28/s), which is what
SQLite's single writer predicts.

```
=== 8 concurrent creates, SAME unique value: product.sku (also the slug_field) ===
status codes: [409, raised IntegrityError, 409, 201, 409, 409, raised IntegrityError, raised IntegrityError]
201 responses: 1   rows actually stored: 1   (correct: 1)

=== 8 concurrent creates, SAME unique value: contact.email (unique, NOT a slug field) ===
status codes: [201, 201, 201, 201, 201, 201, 201, 201]
201 responses: 8   rows actually stored: 8   (correct: 1)
```

### 4.6 Correlated `EXISTS` vs a semi-join from the index

`altquery.py` and `analyze_probe.py`, same filter, same data, one measured
without `ANALYZE`:

| query | correlated `EXISTS` (current) | `IN (SELECT record_id FROM idx WHERE …)` | ratio |
|---|---|---|---|
| `count`, order.ship_state = 'CA' (972 matches) | 60.42 ms | **3.72 ms** | 16.2× |
| page 25, order.total ≥ 900 (36,977 matching index rows) | 249.4 ms | **37.6 ms** | 6.6× |
| `count`, order.total ≥ 900 | **385,503 ms** | **60.6 ms** | **6,361×** |

## 5. Findings, ranked by impact

Each gives the measurement, the plan, the code, the cause, a recommended
change with its expected effect, and its risk. **Nothing was implemented** —
the module is under review and these are findings only.

---

### F1 — On SQLite with no statistics, a filter on a `number`, `date`, `datetime` or `boolean` field is quadratic. A list page can take seven minutes. *(critical, SQLite-specific, one-line mitigation)*

**Evidence.** `GET /api/records/types/order/records?filter=placed_at:gte:2024-01-01T00:00:00Z`
over 45,000 orders: **p50 442,735 ms** (7 m 23 s) for one page of 25. Number
range over 15,000 products: 39,978 ms. Boolean equality over the same 15,000:
14,324 ms — *an indexed boolean filter is 600× slower than no filter at all.*
Three ANDed filters: 410,668 ms.

**Plan.**
```
SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
CORRELATED SCALAR SUBQUERY 1
SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=? AND value>?)
```
The outer loop is over every record of the type. Inside it, SQLite uses the
composite `(type_id, field_key, value)` index to satisfy the *value*
predicate — and `record_id = records_record.id`, the thing that actually
identifies the row, is not in that index, so it is applied as a filter over
the **whole matching value range, once per outer row**. Cost is
(records of the type) × (index rows matching the value predicate): 45,000 ×
~37,000 ≈ 1.7 × 10⁹ index-row visits.

**Cause.** `modules/records/sm_records/index/query.py:164`, `_exists` — the
correlated `EXISTS`. The index definitions
(`models/_index.py:47`, `_index_args`) are right and match the filter's shape;
the problem is that the correlation gives SQLite two usable indexes and, with
no `sqlite_stat1`, it picks the wrong one.

**Fix A (cheap, immediate): run `ANALYZE`.** Measured: `ANALYZE` on the 204 MB
database takes **0.2 s** and turns the 442,735 ms query into **52.59 ms**
(8,418×), the 3-filter AND into 101.52 ms (4,045×), the number range into
21.11 ms and the boolean into 20.68 ms — because the plan flips to
`ix_records_index_datetime_record (record_id=?)`, one probe per outer row.
Nothing else moves by more than 15%. Concretely: have the module run
`ANALYZE` at the end of `reindex_runner.run_pending` (which is already the
"the index changed a lot" moment) and register a
`PRAGMA optimize` on connection close for the SQLite provider.
**Expected effect:** the pathological rows above become ordinary.
**Risk:** low. `ANALYZE` is a read-only statistics pass; the SQLite
documentation recommends `PRAGMA optimize` on close for exactly this. It does
take a write lock briefly, so it should not run inside a request.

**Fix B (structural, backend-independent): emit a semi-join instead of a
correlated `EXISTS`.** `Record.id.in_(select(table.record_id).where(type_id,
field_key, <value clause>))` asks the same question starting from the index
rows that match — which is what design §7.3 describes ("every query joins to
`records_record` by primary key"). Measured without `ANALYZE`: the same
`count` goes from 385,503 ms to **60.6 ms**; a *selective* filter's count goes
from 60.42 ms to **3.72 ms** (16×) — and that 16× survives `ANALYZE`, because
the semi-join is O(matching rows) while the correlated form is O(rows of the
type) however well it is planned.
**Expected effect:** filters become proportional to what they match rather
than to how big the type is, on every backend and with or without statistics.
**Risk:** moderate and worth care. `ne` must become `~Record.id.in_(...)`
(the current code negates the whole `EXISTS`, and the reading "no value
equals x" must be preserved for multi-valued fields — `IN` deduplicates, so
it does). `is_null` likewise. Every case in `tests/test_index_query.py`
should be re-run against the rewritten builder before anything else.

---

### F2 — `unique` is enforced with an unbounded `COUNT` over the same correlated `EXISTS`, so every write to a type with a unique field is O(rows in that type) *(critical, backend-independent)*

**Evidence.** The profiler, at 15,000 products: `ensure_unique` is **20.62 ms
of a 40.93 ms create (50.4%)**. At ~1,000 rows it was 1.98 ms (9.0%). The
growth is linear at ~1.5 µs per existing row:

| rows | `create(product)` (unique) | `create(company)` (no unique) |
|---|---|---|
| 1,000 | 13.24 ms | 10.86 ms |
| 20,000 | 42.37 ms | 12.46 ms |

The seeder is the same curve at full size: `python -m sm_records.cli seed
--records 100000` wrote 5,000 companies quickly and then spent twenty minutes
on 25,000 contacts (`contact.email` is unique), falling from 72 rec/s to
14 rec/s, and **never reached `store` or `order` at all** — 31,400 of 100,000
records in 22 minutes. That is why the dataset for this study had to be built
another way (§2).

**Cause.** `services/_payload.py:143`, `ensure_unique`, line 180:
```python
stmt = count_query(rtype, list(rtype.fields or []), [Filter(field.key, FilterOp.EQ, value)])
…
taken = (await db.execute(stmt.execution_options(include_deleted=True))).scalar_one()
```
`count_query` is the *list-page* count: no `LIMIT`, and the `EXISTS` shape of
F1. The check only needs "does one exist", and it asks "how many are there"
across the whole type. Reusing `count_query` is deliberate and the reason
given (the §7.4 truncation re-check has one owner) is good — the mistake is
the unbounded `COUNT`, not the reuse.

**Fix.** Keep the shared predicate, change the question: build the same
statement and take `select(Record.id).where(…).limit(1)`, or
`select(literal(1)).where(exists)`. Combined with F1's semi-join the check
becomes a single index probe.
**Expected effect:** constant-time uniqueness. On the numbers above, a
`product` create at 15,000 rows drops from 36.2 ms to ~16 ms, and stops
growing; the seeder's 100,000-record run becomes minutes rather than hours.
**Risk:** very low. `exclude_id` and `include_deleted` carry over unchanged;
the truncation re-check is in the predicate, not in the aggregate.

---

### F3 — Concurrent creates with the same unique value all succeed *(correctness; measured on SQLite, unverified on Postgres)*

**Evidence.** Eight concurrent `POST /api/records/types/contact/records` with
an identical `email`: **eight `201`s, eight rows stored.** For
`product.sku` — which is also that type's `slug_field` — the partial unique
index `ix_records_record_type_slug` caught it, but as three unhandled
`IntegrityError`s (HTTP 500 with `db.session.rollback` in the log) rather than
as a 409.

**Cause.** `services/_payload.py:197`, `lock_type` — `SELECT … FOR UPDATE`
compiles to a plain `SELECT` on SQLite, so the check-then-act window design
§7.8 describes is fully open. The README states the mitigation ("writes to a
type with any unique field are serialized") as though it applied everywhere;
on the repo's documented dev default it applies nowhere.

**Fix.** Two independent pieces.
(a) Map `IntegrityError` on the slug index to a 409 in
`endpoints/api/_errors.py`, so the one case the database *does* catch is not a
500.
(b) On SQLite, make `lock_type` take a real write lock when the type has any
unique field — an `UPDATE records_type SET updated_at = updated_at WHERE id =
:id` does it, or open the transaction with `BEGIN IMMEDIATE`.
**Expected effect:** the second writer serialises instead of duplicating.
**Risk:** (b) serialises all writes to that type on SQLite, which is the
documented trade — but it must be gated on `any(field.unique for field in
defs)` so types without a unique field keep concurrent writes. Also verify on
Postgres first (§8.3): if `FOR UPDATE` already closes this there, (b) is a
SQLite-only path.

---

### F4 — Every list page pays an unbounded `COUNT` that the page itself does not need *(high, backend-independent)*

**Evidence.** `count_query(order, ship_state='CA')` measured alone is
**59.55 ms** of the 71.23 ms that whole endpoint call costs. The page query
with `LIMIT 25` is 3.7–6 ms. Under F1's bad plans the split is starker: the
page can stop after 25 matches, the count never can — `page 25` for
`total >= 900` was 249 ms while its `count` was 385,503 ms.

**Cause.** `services/records.py:65`, `list_records`: `total` is computed on
every call, for every page, with the full filter set.

**Fix.** Make the total optional or bounded — `?total=false` for callers that
do not paginate, or a capped count (`SELECT count(*) FROM (… LIMIT 10001)`)
reported as `10000+`. The record list screen could ask for it on page 1 only.
**Expected effect:** removes 70–95% of a filtered list request's cost.
**Risk:** the UI's pager renders a page count. A capped total is a visible
product change ("500+ records"), which is why this is a discussion rather than
a patch.

---

### F5 — Sorting by an indexed field materialises the whole type and builds two temporary B-trees *(high, backend-independent)*

**Evidence.** Every index-field sort, at every kind:
```
MATERIALIZE anon_1
SEARCH records_index_datetime USING INDEX ix_records_index_datetime_lookup (type_id=? AND field_key=?)
USE TEMP B-TREE FOR GROUP BY
SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)
BLOOM FILTER ON anon_1 (record_id=?)
SEARCH anon_1 USING AUTOMATIC COVERING INDEX (record_id=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```
Cost scales with the type, not the page: 19–21 ms sorting 5,000 companies,
134–172 ms sorting 45,000 orders, for 25 rows. Even a **fixed-column** sort
builds a temp B-tree (44 ms at 45,000) although
`ix_records_record_type_status_position` exists.

**Cause.** `index/query.py:191`, `_sorted`: the sort key is a
`GROUP BY record_id` aggregate subquery, outer-joined. Its own docstring says
"one row per record by construction, so a multi-valued field orders the result
without multiplying it" — which is exactly the case where the `GROUP BY` is
unnecessary. The fixed-column temp B-tree comes from `nulls_last(...)` plus
the `Record.id` tiebreaker, which together do not match the existing index.

**Fix.** (a) When the sorted field is single-valued (`multiselect` and
to-many `relation` are the only multi-valued kinds, and the schema knows
which), join the index table directly on `record_id` with the
`(type_id, field_key)` predicate and no aggregate. (b) Drop `nulls_last` for a
`NOT NULL` fixed column (`position`, `created_at`, `status`), so
`ORDER BY position, id` can be served by
`ix_records_record_type_status_position`.
**Expected effect:** removes the materialisation and one of the two temp
B-trees for the common case; the default list sort (`position`, then
`updated_at desc`) becomes index-ordered.
**Risk:** (a) must keep `MIN()` for multi-valued fields, or a product with
three tags appears three times — the current code is correct and the
optimisation must not lose that. (b) is behaviour-preserving only for columns
that really are `NOT NULL`.

---

### F6 — `write_index` issues six `DELETE`s on every write, including on a record that cannot have index rows yet *(medium, backend-independent)*

**Evidence.** 20 statements per `create_record`, six of which are
`DELETE FROM records_index_*`. On a create the row was inserted moments
earlier, so all six are guaranteed to match nothing. Index writing is
**11.14 ms (27.2%)** of a create at 15,000 rows and **10.94 ms (49.6%)** at
1,000 rows — i.e. it is the single largest cost of a create on any type
without a unique field. The purge path issues the same six per record
(`note: purge issues 18 index DELETEs (one per kind table) per record` — three
records in the measured cycle).

**Cause.** `index/writer.py:106` calls `delete_index` unconditionally;
`delete_index` (line 73) loops all six `INDEX_TABLES`. The delete-then-insert
design is right — the comment about drift is correct — but a create knows
there is nothing to delete.

**Fix.** Give `write_index` a `fresh: bool = False` argument that
`create_record` passes; skip `delete_index` when set. Optionally also skip the
tables for kinds the type declares no indexed field of (a `company` never
writes `records_index_ref`).
**Expected effect:** 6 fewer statements and roughly 15–25% off a create.
**Risk:** none for the `fresh` flag — `create_record` is the only caller that
can assert it, and it has just inserted the row. The per-kind narrowing is
riskier (a provider registered by another module can project any kind, design
§7.6), so it should be derived from the entries actually produced, not from
the schema.

---

### F7 — `type_id_map` reads all of `records_type` twice per write *(medium, backend-independent)*

**Evidence.** 0.955 ms/create (2.3%), two of the 20 statements.
`test_type_id_map_per_write` records it.

**Cause.** `services/records.py:140` (`await type_id_map(db)` for the relation
check) and `:178` / `:299` (`await type_resolver(db)`, which calls
`type_id_map` again) — two full `SELECT key, id FROM records_type` per write.

**Fix.** Resolve once in `_prepare` and thread the mapping through to
`write_index`. The table has tens of rows, so this is about round trips, not
volume.
**Expected effect:** ~1 ms and 1 statement per write; more on Postgres, where
a round trip costs more than on an in-process SQLite file.
**Risk:** none.

---

### F8 — The reindex moves ~130 records/s and `reindex_batch_size` barely matters *(medium, backend-independent)*

**Evidence.** Rebuilding 10,000 `store` records: **131 / 134 / 108 rec/s** at
`reindex_batch_size` 100 / 500 / 2000 — 75–93 seconds. A `display_field`
change adds a second whole-type pass at the same rate. Extrapolated to the
45,000-record `order` type that is ~6 minutes during which the field refuses
every filter and sort with a 409 (design §8.5), and the `order` type is only
45% of a 100k install.

**Cause.** `index/reindex.py:42`, `reindex_type` calls `write_index` per
record — so every record costs its own six `DELETE`s (F6) plus individual ORM
inserts plus a flush. Batch size only controls how many `Record` rows are
fetched per round trip, which was never the bottleneck. `field_keys` is
accepted and deliberately ignored.

**Fix.** Two steps, in this order.
(a) Per batch: one `delete_field_rows`-style `DELETE … WHERE record_id IN (…)`
per table, then one `session.execute(insert(Table), [rows])` per table. That
turns ~14 statements per record into ~12 per batch of 500.
(b) *Then*, optionally, honour `field_keys`.
**Expected effect:** (a) alone should be 10–20×, putting a 45,000-record
rebuild under a minute.
**Risk:** (a) is low — the operation is still delete-then-insert over the
same set, just batched, and it stays idempotent. (b) carries exactly the risk
the existing docstring names ("the version that can leave one field's rows
stale if the caller's list is wrong") and should not be attempted until (a)
has shipped.

---

### F9 — The relation picker searches a column no index can serve *(medium, product decision)*

**Evidence.** `components/RelationPicker.tsx:105` issues
`filter=display_title:contains:<term>` on every keystroke (250 ms debounce).
Plan: `SEARCH records_record USING INDEX ix_records_record_type_id (type_id=?)`
and then `ILIKE '%term%'` per row — 20.93 ms over 25,000 contacts, growing
linearly with the type.

**Cause.** `display_title` is a fixed column (design §7.2) and `contains`
compiles to `LIKE '%…%'`, which no B-tree can serve. This is by construction,
not a bug — but it is the one filter an end user types into, on the type they
are least likely to have made small.

**Fix.** Add a `starts_with` operator (`value LIKE 'term%'`) on the *indexed
text* column and have the picker search the target type's `display_field`
instead of `display_title`; `ix_records_index_text_lookup` then serves it.
**Expected effect:** index-backed, constant-time prefix search.
**Risk:** it changes what the picker finds (prefix, not substring), which is a
product decision. The honest long-term answer is a real text index (SQLite
FTS5 / Postgres `tsvector`), which is a bigger piece of work and out of scope
for this review.

---

### F10 — `POST /schema/preview` is a 40-second HTTP request at 45,000 records *(low-medium)*

**Evidence.** `dry_run(order, gift required)` over 45,000 records: **40.6 s**
cold, 6.7 s with the file warm in the page cache; 1,107 rec/s; **`tracemalloc`
peak 4.4 MB**, so the batching does its job and memory is a non-issue.

**Cause.** `services/_dry_run.py` builds a Pydantic model and validates every
record of the type, inline, in the request. Design §8.9 acknowledges this is
not request work and shapes the API for it, but the preview endpoint still
runs synchronously.

**Fix.** Nothing structural is wrong. Either document the ceiling (and the
proxy timeout it implies) or give `preview` the same background-task +
poll treatment the rebuild has.
**Risk:** low either way; the honest minimum is to write the number down.

---

### F11 — `OFFSET` pagination is mild at this scale, and grows *(low)*

**Evidence.** Page 1 of `order` (45,000 records) is 23.52 ms; page 200
(`OFFSET 4975`) is 26.55 ms. About 0.6 µs per skipped row, so page 1,800 —
the last one — would be ~50 ms.

**Cause.** `services/records.py:89`, `offset = max(page - 1, 0) * size`. Worth
noting that three *internal* walks (`reindex_type`, `_dry_run._batches`,
`_orphaned._records`) all deliberately use keyset paging and say why; the
user-facing list is the one place that does not.

**Fix.** None needed for the admin UI. A keyset (`after=<id>`) option on the
JSON API would matter to a caller exporting a whole type.
**Risk:** none; it is an addition.

## 6. Slow because of SQLite, or slow because of the design?

| finding | SQLite artefact | design / code |
|---|---|---|
| F1 range & bool filters quadratic | **Yes** — the plan flips with `ANALYZE`; Postgres keeps statistics automatically and may never pick the bad index | Partly: the correlated `EXISTS` is what *lets* the planner choose badly. Fix B removes the choice. |
| F2 `ensure_unique` is O(type) | No | **Design.** `count_query` without a `LIMIT` is O(type) on any backend. |
| F3 duplicate unique values under concurrency | **Yes** for the *mechanism* (`FOR UPDATE` is a no-op) | The `IntegrityError` → 500 instead of 409 is a code gap on every backend. |
| F4 unconditional `COUNT` per page | No | **Design.** |
| F5 sort materialises the type | Partly — "AUTOMATIC COVERING INDEX" and "TEMP B-TREE" are SQLite's words; Postgres would hash-join and sort | **Design.** The `GROUP BY` subquery is emitted on every backend. |
| F6 six `DELETE`s per create | No | **Code.** Identical statement count on Postgres. |
| F7 `type_id_map` twice per write | No | **Code.** Costs *more* on Postgres (real round trips). |
| F8 reindex at 130 rec/s | Partly (single writer) | **Code.** Per-record ORM writes are per-record everywhere. |
| F9 picker search is a scan | No | **Design/product.** |
| F10 40 s preview | Partly (cold page cache; 6.7 s warm) | **Design** — §8.9 already says so. |
| F11 `OFFSET` | No | **Design**, and mild. |

The honest summary: **two of the eleven findings are SQLite's fault and one of
those has a 0.2-second fix.** The rest are properties of the SQL this module
emits and will reproduce on Postgres.
## 7. What does *not* need attention

Measured, healthy, and worth not optimising:

* **Statement counts are constant in the page size and in the table size.**
  A list page is 3 statements (load type, count, page); the Inertia list view
  is 5 (the two extra are the type header's live/trashed counts); a single
  record GET is 2. None of them grows with rows returned. The Phase 3 review's
  per-row validation on the list screen is genuinely gone —
  `contracts.schemas.record_list_read` computes `field_defs` once and passes
  `with_invalid=False`, and the statement count proves no per-row query
  replaced it.
* **`count_query`'s use of `func.count(Record.id)` rather than a bare
  `count()`.** It reads as a micro-detail; it is what attaches the framework's
  soft-delete filter, and dropping it would count the trash. The plan confirms
  the mapper is in the statement.
* **`diff_fields` touches no database.** A schema preview's entire cost is the
  dry run; the classification itself is free, so there is nothing to cache.
* **The index-row projection itself.** `_payload.validate` (Pydantic) is 0.7%
  of a create and the relation target check is 0.007 ms — neither is worth a
  line of optimisation.
* **The `contains` operator scanning `records_index_text`.** `LIKE '%x%'`
  cannot use a B-tree, and the module documents that. It is a design
  limitation to be *replaced* (with a real text search) rather than tuned.
* **The keyset (`id > last_id`) paging in `reindex_type`, `_dry_run._batches`
  and `_orphaned._records`.** All three deliberately avoid `OFFSET`, and the
  plans show a clean `SEARCH records_record USING INDEX` per batch. The one
  place `OFFSET` survives is the user-facing list (F11), and at this scale it
  costs 3 ms on page 200.
* **`revision_limit` trimming.** It is one extra `SELECT` per write (~10% of a
  create) and it is bounded; the alternative (letting revisions grow) costs
  more.
## 8. What could not be measured here, and how to measure it on Postgres

This container has **no Postgres binary** and none was installed, so
everything above is SQLite 3.45.1. Five things are genuinely open:

1. **Whether the correlated `EXISTS` plans the same way.** Postgres can turn
   `EXISTS` into a hash or nested-loop semi-join and drive from the index
   table; SQLite without statistics did not, and with statistics it chose the
   `record_id` index instead (§4.2). Either Postgres plan removes F1's
   quadratic term, but **neither removes F1's linear term**: the correlated
   form is O(records of the type) however it is planned, while the semi-join
   of Fix B is O(matching rows) — the 16× on a selective filter (§4.6) is the
   part that survives good statistics.
   **How:** `SM_DATABASE_URL=postgresql+asyncpg://…` against the same 100k
   dataset, then `EXPLAIN (ANALYZE, BUFFERS)` on the statement the perf
   suite's statement counter captures. Look for `Hash Semi Join` vs
   `Nested Loop` and at `Rows Removed by Filter`.
2. **Whether Postgres's autovacuum keeps this healthy on its own.** SQLite's
   answer is now known: `ANALYZE` costs 0.2 s and is worth 8,418×. Postgres
   analyses automatically, so F1 should not appear there at all — but a freshly
   restored dump, or a type that has just been bulk-loaded, has no statistics
   either, and that is exactly the state a migration leaves.
   **How:** load the dataset, run the suite *before* the first autovacuum, then
   `ANALYZE` and re-run — the same experiment as §4.2.
3. **Whether `lock_type` closes the `unique` race.** `SELECT … FOR UPDATE` is
   a no-op on SQLite, which is why §4.5 found 8 of 8 concurrent creates with
   the same `contact.email` succeeding. On Postgres the row lock is real and
   the second writer should block.
   **How:** the same `scratchpad/perf/concurrency.py` pointed at Postgres. If
   more than one still succeeds, F3 is a correctness bug rather than a SQLite
   artefact, and the mitigation the README promises does not exist anywhere.
4. **Concurrent-writer throughput.** SQLite serialises every writer, so the
   26.0 creates/s aggregate measured under 8 writers says nothing about a real
   deployment.
   **How:** the same script; expect throughput to scale with writers until
   `lock_type` serialises a type that has a unique field — which is the
   interesting number, because that is the design's documented trade (§7.8),
   and F2 makes the serialised section O(rows in the type).
5. **`Numeric(19, 5)` behaviour.** SQLite stores it as `REAL`, so every number
   filter above compared floats; on Postgres it is an exact decimal. Boundary
   behaviour and the selectivity of `records_index_number` are both untested
   against the real column type.
   **How:** re-run the number cases in `tests/perf/test_read_path.py` on
   Postgres and compare the **match counts**, not just the timings.

Also unmeasured, for want of the fixture rather than the backend:
**multi-worker `reindex_runner` contention** (two workers finishing the same
type's pending rebuild), and **payload sizes near `max_payload_bytes`**
(256 KB) — every record here is a few hundred bytes, so the `json.dumps` size
check in `_payload.validate` never did real work (0.4% of a create).

## 9. Files

* `REPORT.md` (this file) and the trimmed maintainer copy at
  `modules/records/docs/performance.md`
* `modules/records/tests/perf/` — the durable suite
* Raw output: `study_suite.txt` (52-minute 100k run), `study_suite_analyzed.txt`
  (the same read path after `ANALYZE`), `study_profile.txt`,
  `study_concurrency.txt`, `study_altquery.txt`, `analyze_probe.log`,
  `scale_write.log`, `seed_100k.log`, `bulk_100k.log`
* Scripts: `bulk_load.py`, `scale_write.py`, `profile_create.py`,
  `concurrency.py`, `altquery.py`, `analyze_probe.py`, `range_probe.py`,
  `run_study.sh`
* `snap/` — the pinned checkout of `modules/records` at `b13b362` that every
  measurement ran against
