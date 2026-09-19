# Records — performance

What this module costs at scale, measured, and what to watch for. The full
study (raw output, query plans, every command) lives in the PR that added
`tests/perf/`; this is the maintainer's copy.

**Measured on:** SQLite 3.45.1 (file-backed, `journal_mode=delete`, no
`ANALYZE` unless stated), aiosqlite 0.22.1, SQLAlchemy 2.0.51, Python 3.12,
4 cores, single process, HTTP driven in-process through
`tests/app_harness.py`. **No Postgres was available**, so every number is
SQLite; §"On Postgres" below says which findings should reproduce there.

**Dataset:** the five demo types from `sm_records.seed`, 100,000 records —
`order` 45,000, `contact` 25,000, `product` 15,000, `store` 10,000, `company`
5,000 — 747,887 index rows and 100,000 revisions, 204 MB.

## Run the suite yourself

```
cd modules/records && uv run pytest -m perf tests/perf
```

It is excluded from the default run (`addopts = "-m 'not perf'"`).
`RECORDS_PERF_N` sets the dataset size (default 2000, about a minute),
`RECORDS_PERF_REPS` the repetitions (default 20), `RECORDS_PERF_BUDGET` the
seconds one measurement may spend, and `RECORDS_PERF_DB` points it at a
database seeded elsewhere. It prints a results table and the
`EXPLAIN QUERY PLAN` of each operation's heaviest statement, and asserts only
shapes — "a filtered list does not full-scan `records_record`", "a page costs
a constant number of statements" — never wall-clock thresholds.

## The two things to know

### 1. Run `ANALYZE` on SQLite. It is worth four orders of magnitude.

Without statistics SQLite plans the filter's correlated `EXISTS`
(`index/query.py:_exists`) by using the `(type_id, field_key, value)` index
for the *value* predicate and then filtering the whole matching range by
`record_id`, once per record of the type. With statistics it uses the
`(record_id)` index instead — one probe per row.

| filter | no `ANALYZE` | after `ANALYZE` (0.2 s) |
|---|---|---|
| `placed_at:gte:…` over 45,000 orders | **442,735 ms** | **52.59 ms** |
| three ANDed filters, 45,000 orders | 410,668 ms | 101.52 ms |
| `price:gte:100` over 15,000 products | 39,978 ms | 21.11 ms |
| `in_stock:eq:true` over 15,000 products | 14,324 ms | 20.68 ms |
| `founded:gte:1990-01-01` over 5,000 companies | 3,386 ms | 13.17 ms |
| text / select / multiselect / ref filters | 17–136 ms | unchanged |

Nothing in this module or its migrations runs `ANALYZE`. Until something
does, a SQLite install with a populated type and a `number`/`date`/`datetime`/
`boolean` filter is unusable.

A `Record.id.in_(select(idx.record_id).where(…))` semi-join removes the
planner's chance to get it wrong at all, and is additionally **16× faster
than the correlated form on a selective filter even after `ANALYZE`** (a
`count` of 972 matching orders: 60.42 ms → 3.72 ms), because it is
proportional to what matches rather than to the size of the type.

### 2. A `unique` field makes every write to that type O(rows in the type).

`_payload.ensure_unique` checks uniqueness with `count_query` — the list
page's count, with no `LIMIT`, over every record of the type.

| rows in the type | `create(product)`, unique `sku` | `create(company)`, no unique field |
|---|---|---|
| 1,000 | 13.24 ms (75 rec/s) | 10.86 ms (92 rec/s) |
| 5,000 | 18.81 ms (53 rec/s) | 11.06 ms (90 rec/s) |
| 10,000 | 26.91 ms (37 rec/s) | 10.22 ms (98 rec/s) |
| 20,000 | 42.37 ms (24 rec/s) | 12.46 ms (80 rec/s) |

At 15,000 rows the check is **50.4% of a create**; at 1,000 it is 9.0%. The
demo seeder is the same curve at full size: `--records 100000` wrote 31,400
records in 22 minutes and never reached the `order` type, its rate falling
from 72 rec/s to 14 rec/s across 25,000 contacts with a unique `email`.

The check only needs "does one exist"; asking `COUNT(*)` over the whole type
is what makes it linear.

## Reference numbers at 100,000 records

Read path, through `GET /api/records/…`, p50 over 20 repetitions. Every list
operation is **3 SQL statements** (load type, count, page) regardless of page
size or table size; a single record GET is 2; the Inertia list view is 5.

| operation | type size | p50 ms |
|---|---|---|
| list page 1, unfiltered | 45,000 | 23.5 |
| list page 200 (`OFFSET 4975`) | 45,000 | 26.6 |
| single record by uuid | 45,000 | 3.8 |
| text `eq` / `contains` | 5,000 | 17.5 / 17.3 |
| select `eq` | 45,000 | 71.2 |
| multiselect `eq` | 15,000 | 36.1 |
| ref `eq` | 45,000 | 136.4 |
| `in` with 50 values | 25,000 | 72.8 |
| number / date / datetime / bool filters | see §1 — run `ANALYZE` | |
| sort by an indexed field | 5,000 / 15,000 / 45,000 | 19–21 / 33–40 / 135–172 |
| sort by a fixed column | 45,000 | 40–44 |
| the count alone, for one filtered page | 45,000 | 59.6 |
| Inertia `/admin/records/order` | 45,000 | 60.3 |

Write path:

| operation | p50 ms | statements |
|---|---|---|
| `create_record`, type has no unique field | 14.4 | 20 |
| `create_record`, type has a unique field (15,000 rows) | 36.2 | 21 |
| `update_record`, indexed field changed / unchanged | 36.2 / 35.6 | 22 / 21 |
| trash → restore → trash → purge | 40.3 | 53 |

Where one create's 40.93 ms goes at 15,000 rows: `ensure_unique` 20.62 ms
(50.4%), index rows 11.14 ms (27.2%), revision insert + trim 2.30 ms,
`lock_type` 1.09 ms, `ensure_slug_free` 1.08 ms, `type_id_map` 0.96 ms
(it runs **twice** per write), `field_defs` 0.59 ms, Pydantic validation
0.16 ms, relation target check 0.006 ms.

Schema operations:

| operation | records | wall time | notes |
|---|---|---|---|
| `POST /schema/preview` dry run | 45,000 | 40.6 s cold / 6.7 s warm | 1,107 rec/s, `tracemalloc` peak **4.4 MB** |
| `run_pending` rebuild, `reindex_batch_size` 100 / 500 / 2000 | 10,000 | 76.3 / 74.9 / 92.7 s | **131 / 134 / 108 rec/s** — batch size barely matters, and 2000 is worse |
| `display_field` change (whole-type rebuild) | 10,000 | 76.3 s | a second full pass on top of the index rebuild |
| `_orphaned.count_conflicts` / `.discard` | 10,000 | 0.26 s / 0.87 s | both fine |
| type revision rollback (no field change) | — | 12 ms | |

A 45,000-record type therefore spends about **6 minutes** in `reindex_pending`
after an index-affecting schema change, refusing that field as a filter with a
409 the whole time.

Concurrency (8 asyncio writers, in-process client): 200/200 creates in 7.71 s,
**26.0 creates/s aggregate** — slightly below single-writer throughput, which
is what SQLite's single writer predicts. No `database is locked`.

## Known sharp edges

* **`unique` is racy.** Eight concurrent creates with the same
  `contact.email` all returned 201 and all eight rows were stored.
  `_payload.lock_type`'s `SELECT … FOR UPDATE` is a no-op on SQLite, so the
  check-then-act window design §7.8 describes is fully open there. Where the
  unique field is also the type's `slug_field` (`product.sku`) the partial
  unique index catches it — but as an unhandled `IntegrityError`, i.e. a 500
  rather than a 409. Unverified on Postgres, where the row lock is real.
* **Every list page computes an unbounded total.** The count is 59.6 ms of a
  71.2 ms filtered request; the page query itself is 4–6 ms. The page can stop
  after 25 matches, the count never can.
* **A sort on an indexed field materialises the whole type**
  (`MATERIALIZE` + `TEMP B-TREE FOR GROUP BY` + `AUTOMATIC COVERING INDEX` +
  `TEMP B-TREE FOR ORDER BY`), so its cost scales with the type rather than
  the page. The `GROUP BY record_id` aggregate is only needed for
  `multiselect` and to-many `relation`.
* **`write_index` issues six `DELETE`s on every write**, including on a create
  where the record cannot have index rows yet — 27–50% of a create's time.
* **The relation picker searches `display_title` with `contains`**
  (`RelationPicker.tsx`), which is `ILIKE '%term%'` on `records_record` and
  cannot use any index: 20.9 ms over 25,000 contacts, growing linearly, on
  every keystroke after the debounce.
* **The reindex rewrites each record's rows individually.** Batching the
  `DELETE`/`INSERT` per batch instead of per record is where its 130 rec/s
  would come from.

## What is already fine

* Statement counts are constant in rows returned and in table size.
* The Phase 3 list-page validation cost is gone — `record_list_read` computes
  `field_defs` once and skips the per-row `invalid` pass.
* `count_query`'s `func.count(Record.id)` (rather than a bare `count()`) is
  what attaches the soft-delete filter; do not "simplify" it.
* The batched schema passes are memory-safe: 4.4 MB peak over 45,000 records.
* The keyset paging in `reindex_type`, `_dry_run._batches` and
  `_orphaned._records` is correct and shows clean index use.
* Pydantic validation (0.4% of a create) and the relation target check
  (0.006 ms) are not worth optimising.

## On Postgres

Untested here — no Postgres binary was available. Expectations:

* The **statement counts and the code-shape findings** (`write_index`'s six
  deletes, `type_id_map` twice per write, the per-record reindex, the
  unbounded `COUNT` in `ensure_unique` and in every list page) are identical
  on any backend, and the round-trip ones cost *more* there.
* The **`ANALYZE` finding should not appear**, since autovacuum keeps
  statistics — except immediately after a restore or a bulk load, which is
  exactly the state a migration leaves.
* The **semi-join advantage should remain**, because it is proportional to
  matches rather than to the type.
* **`lock_type` should actually lock**, which would make the `unique` race
  SQLite-only. Verify it before relying on it: run the perf suite's
  concurrency scenario against Postgres and count the 201s.
