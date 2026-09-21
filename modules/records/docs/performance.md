# Records — performance

What this module costs at scale, measured, and what to watch for. The full
study that found these — raw output, query plans, every command — is
[`perf-study-2026-09-19.md`](perf-study-2026-09-19.md); this is the
maintainer's copy, and it is the one that says what has since been **fixed**.

**Measured on:** SQLite 3.45.1 (file-backed, `journal_mode=delete`, the
seeder's own `ANALYZE` and no other unless stated), aiosqlite 0.22.1,
SQLAlchemy 2.0.51, Python 3.12, single process, HTTP driven in-process through
`tests/app_harness.py`. Every number below is SQLite unless it says otherwise —
and since the Phase 5 round some of them do: **PostgreSQL 16.13 was available**
(a local cluster, `C.UTF-8`, `shared_buffers` 256 MB), and §"On Postgres" is
measurements rather than expectations. The S1–S5 round adds a Postgres
before/after for S2 and S3, taken on one database back to back.

**Datasets.** The original study ran at 100,000 records. The before/after
tables below are the durable suite at its two reproducible sizes,
`RECORDS_PERF_N=2000` and `RECORDS_PERF_N=20000`, seeded by `sm_records.seed`
into the five demo types (`order` 45%, `contact` 25%, `product` 15%, `store`
10%, `company` 5%). At 20,000 that is 9,000 orders, 5,000 contacts, 3,000
products, 2,000 stores and 1,000 companies. The two runs of each pair start
from **byte-identical copies of one seeded file**, so a row of a table below
is one code change and nothing else. The S1–S5 pair is two whole-suite runs
back to back on **one** file, the first against the same tree with
`sm_records/` reverted — which is the closest a pair can get, and still leaves
a drift of ±20 % that every table in §S1–S5 names a control row against.

## Run the suite yourself

```
cd modules/records && RECORDS_PERF_N=<n> ../../.venv/bin/python -m pytest -q -s -m perf tests/perf -p no:cacheprovider
```

It is excluded from the default run (`addopts = "-m 'not perf'"`), and `-s` is
load-bearing: the results table is printed from a session fixture, so pytest
captures it without it. `RECORDS_PERF_N` sets the dataset size (default 2000,
about a minute), `RECORDS_PERF_REPS` the repetitions (default 20),
`RECORDS_PERF_BUDGET` the seconds one measurement may spend, and
`RECORDS_PERF_DB` points it at a SQLite file seeded elsewhere and
`RECORDS_PERF_URL` at a whole other backend (`postgresql+asyncpg://…`; the
tests that mutate their database skip there, because `perf_db_copy` copies a
file). A database seeded
before a revision added an index picks it up on the next run — `create_all` is
`checkfirst` per *table* and would otherwise keep measuring the old schema
against the new code. That recovery runs on **either** backend and `ANALYZE`s
what it created, because a SQLite index with no statistics row is not neutral
(§S2). It prints a results table and the
`EXPLAIN QUERY PLAN` of each operation's heaviest statement — which since F4
is often the bounded count rather than the page, so a *page* plan is worth
taking by hand — and asserts only shapes: "a filtered list does not full-scan
`records_record`", "a create issues no index `DELETE`s", "a page costs a
constant number of statements", "`total=false` costs one statement less".
Never wall-clock thresholds.

## Fixed

All sixteen findings — the original study's eleven (F1–F11) and the five the
Phase 5 round left open (S1–S5). Each row is p50 over 20 repetitions on the
same seeded file, before → after.

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
`_prefix.prefix_range` produces `term <= value < successor(term)` instead,
stepping over the surrogate block and returning no upper bound for a term of
maximum code points. The comparison is pinned to code-point order
(`_prefix.ByteOrdered`: `COLLATE "C"` on Postgres, the bare column elsewhere),
because under a linguistic collation such as the `postgres` image's
`en_US.utf8` the plain range also answered the other case (`'item' <= 'ITEM' <
'iten'`). On such a cluster the range no longer seeks the `value` btree past
its `(type_id, field_key)` prefix; it reads that field's rows and filters. The
cost is that `starts_with` is case-sensitive where `contains` is not — which
is why the picker asks in that order and why both operators exist.

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

### S1 — the public read paid for content i18n on a monolingual install

`endpoints/api/public.py` called `published_siblings(...)` on **every** public
list response and **every** public record read, with no test of how many
languages the install publishes in. On a host whose `content_locales` is
`("en",)` every record is alone in its own translation group, so the statement
could only ever return the records it was handed — one extra round trip on the
two endpoints anonymous traffic hits hardest, on the install that never asked
for the feature. It now returns `{}` without issuing anything when there is one
content locale, and `endpoints/views.py`'s editor — which fills `translations`
unconditionally for a Languages panel that is not rendered below two locales —
skips its own read the same way.

| operation, 1 content locale, ~1,150 companies | before | after |
|---|---|---|
| `GET {public_prefix}/company` — **statements** | **4** | **3** |
| the same, p50 | 12.77 ms | **9.81 ms** |
| `GET {public_prefix}/company/{uuid}` — **statements** | **3** | **2** |
| the same, p50 | 5.09 ms | **3.83 ms** |
| `GET /api/records/types/company/records` (admin, the control) | 11.27 ms, 3 | 10.91 ms, 3 |

Both statement counts are now the Phase 4 ones, and
`test_one_locale_is_the_phase_4_read_path` asserts them rather than noting them
— "inert when unused" is a promise about code, not a measurement of a machine.
The `translations` array a monolingual host serves is empty where it used to
carry the record itself; nothing can be built from either, since there is no
second language to switch to, and `test_a_decommissioned_locale_is_not_served_publicly`
says so.

### S2 — on Postgres, a descending sort on a nullable fixed column could not use its index

F5 gave `position`, `published_at`, `updated_at`, `created_at`, `display_title`
and `slug` a `(type_id, <column>, id)` index each, and `index/_sorting` drops
`NULLS LAST` only where the mapper says the column is `NOT NULL`.
`published_at`, `updated_at` and `slug` are not, so `ORDER BY col DESC NULLS
LAST, id DESC` is **neither direction** of their ascending btree: read backwards
it yields `DESC NULLS FIRST`. Postgres ignored the index and sorted the whole
type to return 25 rows.

`models/_record_args.add_descending_indexes` now declares a second index per
nullable sortable column, in the order the page asks for —
`(type_id, <column> DESC NULLS LAST, id DESC)`, once per table set, created by
revision **`c4a17b9de0f2`**. On SQLite the same declaration compiles to
`(type_id, <column> DESC, id DESC)`: SQLite has no `NULLS` clause in `CREATE
INDEX` at all (`unsupported use of NULLS LAST`) and needs none, because it sorts
`NULL` smallest and `DESC` already puts them last.

**Postgres, 9,000 orders** (`GET /api/records/types/order/records?sort=…`):

| sort | before | after | |
|---|---|---|---|
| `-updated_at` (nullable) | 30.82 ms | **19.24 ms** | −38 % |
| `-published_at` (nullable) | 29.60 ms | **20.00 ms** | −32 % |
| `updated_at` (control) | 20.76 ms | 19.23 ms | |
| `published_at` (control) | 23.99 ms | 23.39 ms | |
| `position` / `-position` (`NOT NULL`, control) | 19.75 / 18.97 ms | 19.15 / 19.37 ms | |

The plan is the finding. Before:

```
-- page 1, sort -updated_at
Limit
  ->  Sort  (cost=1122.57..1145.07 rows=9000)
        Sort Key: updated_at DESC NULLS LAST, id DESC
        ->  Index Scan using ix_records_record_type_id on records_record
              Index Cond: (type_id = 5)
```

After:

```
-- page 1, sort -updated_at
Limit  (cost=0.29..9.40 rows=25)
  ->  Index Scan using ix_records_record_type_updated_desc on records_record
        Index Cond: (type_id = 5)
```

`-published_at` is the same pair, on `ix_records_record_type_published_desc`.
The sort of 9,000 rows is gone; what remains is an index scan that stops after
25. It is a *forward* scan of a descending index rather than the `Index Scan
Backward` one might expect — the index is stored in the order the query asks
for, so there is nothing to reverse.

**On SQLite the index buys nothing, and creating it without `ANALYZE` costs a
great deal.** SQLite sorts `NULL` smallest, so `DESC` already means `DESC NULLS
LAST` there and the ascending index has served these sorts all along:

```
-- page 1, sort -updated_at
before:  SEARCH records_record USING INDEX ix_records_record_type_updated_id (type_id=?)
after:   SEARCH records_record USING INDEX ix_records_record_type_updated_desc (type_id=?)
```

No temp B-tree either way, and no sorter either way — the two indexes are the
same walk read in two directions, and with statistics SQLite picks the new one
because it is now there. What is new is a third index on
`(type_id, …)` that **no `sqlite_stat1` row describes**, and to SQLite's planner
that is not "unknown" but *assumed to be very selective*. On a database whose
other indexes were analysed (the seeder runs `ANALYZE`, `seed/runner.py`) the
new one therefore won every `type_id = ?` lookup it was eligible for — including
the ones whose `ORDER BY` it cannot produce:

| same file, same rows, A/B on the three indexes alone | analysed | created, not analysed |
|---|---|---|
| list page 1, no sort | 1.11 ms, `ix_records_record_type_id` | **26.52 ms**, `…_updated_desc` + `TEMP B-TREE` |
| list page 200, no sort | 2.38 ms | **45.30 ms**, same |
| list page 1, `sort=position` | 1.10 ms, `…_type_position_id` | **27.58 ms**, same |
| list page 1, `sort=-updated_at` | 1.15 ms | 1.11 ms, `…_updated_desc` (correct) |

One `ANALYZE` per document table puts every plan back, and that is what
revision `c4a17b9de0f2` does after creating the indexes — the same claim
`index/_analyze.py` already makes for the end of a reindex and the end of a
seeding run, made once more for the moment that adds an index. The perf
suite's `_create_missing_indexes` does it too, so a reused seeded file is in
the state a migrated install is in rather than the state above.

**It is the more general finding.** Any revision that adds an index to a table
whose other indexes are analysed leaves SQLite planning against a statistic it
does not have, and the symptom is not the new query being slow — it is every
*old* query picking the new index.

With statistics, the SQLite rows move inside the instrument's drift:

| SQLite, 9,000 orders | before | after | |
|---|---|---|---|
| sort `-updated_at` | 17.87 ms | 15.53 ms | −13 % |
| sort `-published_at` | 17.60 ms | 15.42 ms | −12 % |
| sort `position` (nothing here touches it) | 17.49 ms | 15.53 ms | −11 % |
| `create_record(company)` (13 statements) | 12.58 ms | 10.92 ms | −13 % |
| `create_record(product)` (14 statements) | 14.34 ms | 11.50 ms | −20 % |
| `update_record`, no indexed change (20 statements) | 17.81 ms | 14.70 ms | −17 % |
| `GET /order/records` with total (the control) | 17.67 ms | 17.81 ms | +1 % |
| export the type as JSON (the control) | 1,410 ms | 1,443 ms | +2 % |

**Read the whole column, not a row of it.** `position` is in that table because
no part of this change can touch it, and it moved by the same −11 % as the two
sorts that are the subject: the two runs were back to back on one file and the
second found it warm. What the pair says is that nothing moved *structurally* —
same statement counts, same plans — and that three more btree inserts per record
written did not show up in the write rows. §F5's own note applies unchanged: it
did not measurably move for the first six and it does not for these.

### S3 — on Postgres, the keyset cursor filtered after the join

`?after=` beats `?page=` because it does not produce and discard 4,975 rows, but
the keyset predicate was written out as an `OR` of three comparisons — and an
`OR` is what stops a planner pushing a predicate into an index scan.
`index/_sorting.keyset_clause` now emits the row-value comparison
`(col, id) > (:v, :id)` for the one shape where it means exactly the same thing:
a **single, non-nullable** sort term whose tiebreaker runs the same way. Both
backends support row values (Postgres always, SQLite since 3.15), so nothing
here tests for a dialect; what decides is the shape of the sort.

The `OR` expansion stays for everything else, and that is not a leftover.
`NULLS LAST` is an ordering a row value cannot express — SQL says a comparison
against `NULL` is unknown, the ordering says nothing is after it — and every
sort on an *indexed* field is nullable, because it is reached by `LEFT OUTER
JOIN`. Several terms, and a descending term whose tiebreaker stays ascending,
are the other two.

**Postgres, page 200 of 9,000 orders by `?after=`:**

| sort | before | after | |
|---|---|---|---|
| `created_at` (`NOT NULL`, row value) | 14.33 ms | **13.52 ms** | 2 statements |
| `-created_at` (`NOT NULL`, row value) | 14.74 ms | **13.09 ms** | 2 statements |
| `-placed_at` (indexed, nullable — the `OR` form, unchanged) | 29.62 ms | 29.74 ms | 2 statements |
| the same page by `?page=` (`OFFSET 4975`) | 41.47 ms | 41.32 ms | 3 statements |

Before:

```
Limit
  ->  Index Scan using ix_records_record_type_created_id on records_record  (cost=0.29..3389.37)
        Index Cond: (type_id = 5)
        Filter: ((created_at > '…') OR ((created_at = '…') AND (id > 15975)))
```

After:

```
Limit
  ->  Index Scan using ix_records_record_type_created_id on records_record  (cost=0.29..2125.94)
        Index Cond: ((type_id = 5) AND (ROW(created_at, id) > ROW('…', 15975)))
```

The predicate moved from `Filter` to `Index Cond`: it is now part of what the
scan seeks to rather than what it discards afterwards. `-placed_at`'s plan is
unchanged, `Hash Left Join` and all — that is the case the row value cannot
express, and it is recorded here so nobody looks for a regression that is a
design decision.

**SQLite** narrows the same scan:

```
-- page 200 by cursor, sort created_at
before:  SEARCH records_record USING INDEX ix_records_record_type_created_id (type_id=?)
after:   SEARCH records_record USING INDEX ix_records_record_type_created_id
             (type_id=? AND created_at>?)
```

The predicate is an index constraint there too, and SQLite reports the leading
column of the tuple rather than the tuple — the row value is what let it move
out of the filter at all.

| SQLite, page 200 by cursor, 9,000 orders | before | after |
|---|---|---|
| `sort=created_at` (row value) | 10.97 ms | 9.43 ms |
| `sort=-created_at` (row value) | 10.81 ms | 9.57 ms |
| `sort=-placed_at` (the `OR` form, unchanged) | 19.88 ms | 23.80 ms |

`-placed_at` is the row that did not change and the row that moved most, which
is worth saying out loud: its predicate is the same `OR` it always was, and its
plan is the same join plus temp B-tree, but `records_record` is now reached
through `ix_records_record_type_published_desc` instead of
`…_type_published_id` — two interchangeable `(type_id, …)` indexes that SQLite
chooses between on statistics, exactly the equivalence
`tests/perf/test_collections.py::_shape` normalises away. 20 % is what that
choice is worth on this row and it is not a property of the cursor.

The pages are byte-identical either way, which is the point and which the
measurement asserts: `test_deep_page_by_cursor_on_a_non_nullable_column`
compares them against `?page=`, `tests/test_cursor_keyset.py` walks a whole type
by cursor and compares that against one unpaged read, and the offset-vs-cursor
equality test that predates this is untouched and still green.

### S4 — import was 816 rows/s, and an `abort` paid it in full before refusing

Two halves, both in the planning pass.

**`unchanged()` compared through `read_view`.** Every row rendered its stored
record to the current schema (a lenient per-field coercion) and walked the
result back through `to_jsonable` to compare it field by field — on an import
that writes nothing, which is what re-importing an export is. It now hashes two
normalised payloads instead: `json.dumps(…, sort_keys=True)` over
`record.data` and over `row.stored`, both of which are *already* in stored form.
That is sound because of the line above it — a record whose `schema_version` is
behind the type's is "changed" by rule (the restamp is the lazy migration), so
by the time the payloads are compared the record has already been written under
this exact schema and there is nothing for `read_view` to reconcile.

**`abort` validated the whole file before refusing.** Nothing is going to be
written, so the rest of the pass only decides how long the refusal takes. A real
`on_error=abort` run now stops at the first row that fails, in the parse, the
validation or the planning pass. The report names one row instead of up to
`ERROR_CAP` of them — a dry run, which is what the caller asks for when it wants
the whole list, is unchanged, and so is `on_error=skip`, which is going to write
every row that is fine.

Measured on its own, two runs of `tests/perf/test_io.py` back to back against
copies of the same file, because the whole-suite pair has a drift of ±20 % and
these are the only rows in it that are not a single query:

| SQLite, 9,000 orders | before | after | |
|---|---|---|---|
| import an unchanged export, `upsert` (every row skipped) | 10,919 ms — **824 rows/s** | 9,810 ms — **917 rows/s** | −10.2 % |
| `on_error=abort`, bad row **last** of 9,000 | 10,738 ms to refuse | 9,182 ms | −14.5 % |
| export the same type as JSON (the control) | 1,393 ms | 1,381 ms | −0.8 % |
| export as CSV (the control) | 1,517 ms | 1,515 ms | −0.2 % |

The controls are what make the other two readable: the exporter is code neither
run touched and it moved by under a percent, so the 10 % and the 14.5 % are the
change and not the machine. The abort row is the worst case by construction —
the bad row is the *last* one, so the short-circuit saves the planning pass and
nothing of the validation pass; a file that fails early now refuses in
proportion to where it fails rather than to its length.

The round trip still parses, coerces and validates every row against the
compiled model — that is the expensive half and it stays, because it is what
makes an import safe. What is gone is the second schema pass per row.

`test_import_the_export_back_in_upsert_mode` still asserts
`skipped == total` and an unchanged record count, and the module's idempotence
and round-trip tests are green: the digest answers the same question the deep
comparison did.

### S5 — `referrers()` cost one read per **declared** collection

Not per *used* one. The walk asked every table set in turn — a `UNION` would
merge ids that mean different rows, because two collections number their records
independently (§6.6) — so a host that declared two collections paid three reads
on every `restrict` delete and every referrers panel even when both collections
were empty. That is linear in declarations, and a host's declarations are its
Alembic history, which only ever grows.

`services/_referrer_sets.referring_sets` now asks `records_type` once which sets
hold a type declaring a relation to this record's type, and the loop runs over
those. Three ways out return every set unchanged: a host with **no** collection
declared (one set — the narrowing could only add a query, and the default host
must not pay for a feature it does not use), a `type_id` no `records_type` row
carries, and an install with a registered index **provider** that projects `REF`
entries, since a provider may point at a type from a set whose schema says
nothing about it (§7.6).

| `referrers()` on a type nothing relates to | before | after |
|---|---|---|
| 1 declared collection | 2 statements, 1.36 ms | **1 statement**, 0.66 ms |
| 2 declared collections | 3 statements, 2.17 ms | **1 statement**, 0.67 ms |
| 0 declared collections (the default host) | 1 statement | 1 statement |

The increment is what matters and it is now zero: declaring a collection a type
never relates to is free. `test_referrers_costs_nothing_per_declared_table_set`
asserts the count directly, and `test_collections_relations.py` asserts the
other half — that the set which *can* hold a referrer is still asked, in both
directions across the boundary, because reading too few tables is a `restrict`
that lets a delete through.

Deliberately **not** memoised per session, although `plan_delete` walks a cascade
one record at a time: a memo would make the second call of a request free and
the number a test can assert depend on how many calls came before it. The query
it saves is up to one *per declared collection* on each of those records, so the
walk is ahead everywhere except on a host where every declared collection holds
a type pointing at this one — where it is behind by exactly one statement.

## Phase 5 — what the features cost, and what they cost when nobody uses them

Phase 5 built five things the original design had deferred: import/export,
content i18n, live aggregates with opt-in reduce indexes, collections, and the
pagebuilder widget. [The design's §0](../../../docs/plans/2026-09-20-records-phase5-design.md)
makes one promise about all of them — *"each is opt-in per type or per host,
off by default, and **inert when unused**: a host that never sets `collection`
on a type, never registers a reduce provider, and never enables a second
content locale runs exactly the Phase 4 code paths"* — and this section is
that promise as numbers, plus the price of each feature once it is switched on.

**Three trees, one dataset.**

| tree | what it is |
|---|---|
| `d5f4e0f` | the head after the *first* perf fixes (F1, F2, F3, F6, F7, F8) — before Phase 4 |
| `cd82e9a` | Phase 5 §1, closing F4/F5/F9/F10/F11 — the last commit before any Phase 5 **feature** |
| `da162c6` | Phase 5 complete (collections, the last wave) |

`RECORDS_PERF_N=20000` — 1,000 companies, 5,000 contacts, 3,000 products,
2,000 stores, 9,000 orders — **median of three whole-suite runs per tree**, each
run starting from its own fresh copy of the seeded file. Three runs and not one
because a single run of this suite is not repeatable to better than about a
tenth: `GET company list, text eq (city)` measured on `cd82e9a` in three
separate batches gave **8.87, 9.48 and 9.99 ms** — a 12.6 % spread for one
commit against one file. That number is the instrument's own drift and every
delta below has to be read against it.

**The read path and the pagination rows run on byte-identical copies of one
file**, seeded by the current tree: the Phase 5 columns are additive and the
older code simply does not select them, so both baselines read the same bytes.
Writing to it is a different matter — `records_record.locale` and
`translation_group` are `NOT NULL`, so an insert from a pre-i18n tree fails the
constraint, and the conftest's `_create_missing_columns` recovers only
*nullable* columns by design. The **write-path** rows therefore run on a second
file seeded by `d5f4e0f` itself. The two files are the same dataset from the
same seed — identical record counts per type and identical total payload and
slug bytes, verified column by column; they differ only in the uuids relations
point at and in the wall-clock stamps, neither of which any measurement reads.
The **schema-operation** rows are back on the one shared file, because those
tests only read and update.

`da162c6` is where Phase 5's code stops; the review and browser-QA commits
that follow it are not in these numbers, and nothing in them touches the query
layer. Re-running is one command per tree — see §"Run the suite yourself".

> `cd82e9a` does not import. Its `endpoints/api/__init__.py` names
> `from sm_records.endpoints.api import io`, and `io.py` arrives one commit
> later in `4da519f` — the import/export router's mount leaked into the perf
> commit. The baseline worktree needed a two-line patch (drop `io` from the
> import and its `include_router`) before anything could run against it.
> Nothing else in the study depends on it, but a bisect that lands there stops
> dead, so it is worth knowing.

### Inert when unused — the write path

Nothing about a write changed. The statement counts are identical across all
three trees, and so are the milliseconds:

| write | `d5f4e0f` | `cd82e9a` | `da162c6` | statements |
|---|---|---|---|---|
| `create_record(company)` — no unique field | 14.05 ms | 14.89 ms | **14.75 ms** | **13**, all three |
| `create_record(product)` — unique `sku` | 15.37 ms | 15.43 ms | **15.25 ms** | **14**, all three |
| `update_record`, no indexed change | 18.59 ms | 19.61 ms | **19.45 ms** | **20**, all three |
| `update_record(price)` | 19.79 ms | 19.71 ms | **19.41 ms** | **21**, all three |
| trash → restore → trash → purge | 48.28 ms | 48.54 ms | **52.76 ms** | **46**, all three |

13 and 14 are the numbers F2 + F6 + F7 left behind, and they are still the
numbers. The purge cycle is the one row over 5 %, and it is the one row in this
table measured on two different files; at 4.5 ms over a four-write cycle it is
inside the drift quoted above either way.

The suite asserts the parts of this that are properties of the code rather than
of the machine: `test_create_statement_count_is_flat` (the count does not move
between the 1st and the 51st write), `test_type_id_map_is_resolved_once_per_write`,
and — new in this round —
`test_a_write_costs_nothing_when_no_spec_is_registered`, which fails if a write
touches `records_index_reduce` on a host that registered no reduce provider.

### Inert when unused — the read path

Every row of the read path and the pagination suite, `cd82e9a` → `da162c6`,
median of three. **No row moved more than 12 %, in either direction, and not
one statement count or query plan changed.**

| operation | type size | `cd82e9a` | `da162c6` | | statements |
|---|---|---|---|---|---|
| `GET /order/records` page 1 | 9,000 | 19.06 ms | 19.54 ms | +2.5 % | 3 |
| the same with `?total=false` | 9,000 | 11.18 ms | 11.99 ms | +7.2 % | 2 |
| page 200 by `?page=` (`OFFSET 4975`) | 9,000 | 72.77 ms | 80.86 ms | +11.1 % | 3 |
| page 200 by `?after=` | 9,000 | 22.11 ms | 23.57 ms | +6.6 % | 2 |
| text `eq` (city) | 1,000 | 9.99 ms | 10.67 ms | +6.8 % | 3 |
| text `contains` | 1,000 | 15.63 ms | 16.53 ms | +5.8 % | 3 |
| select `eq` (ship_state) | 9,000 | 15.32 ms | 16.27 ms | +6.2 % | 3 |
| ref `eq` (customer) | 9,000 | 10.42 ms | 10.79 ms | +3.6 % | 3 |
| multiselect `eq` (tags) | 3,000 | 15.77 ms | 16.04 ms | +1.7 % | 3 |
| number / bool / date / datetime range | 1,000–9,000 | 15.02–26.45 ms | 16.33–27.78 ms | +3.6…+8.7 % | 3 |
| three ANDed filters | 9,000 | 49.45 ms | 51.00 ms | +3.1 % | 3 |
| `in` with 50 values | 5,000 | 18.69 ms | 19.23 ms | +2.9 % | 3 |
| sort by `placed_at` / `-placed_at` | 9,000 | 27.96 / 27.84 ms | 30.15 / 29.22 ms | +7.8 / +5.0 % | 3 |
| sort by `customer` / `-customer` | 9,000 | 31.23 / 31.97 ms | 33.15 / 33.57 ms | +6.1 / +5.0 % | 3 |
| sort by `tags` (the `MIN` aggregate) | 3,000 | 24.34 ms | 26.44 ms | +8.6 % | 3 |
| sort by a fixed column (6 rows) | 9,000 | 18.38–20.02 ms | 19.81–20.38 ms | −1.0…+9.7 % | 3 |
| single record by uuid | 9,000 | 5.07 ms | 5.51 ms | +8.7 % | 2 |
| picker `starts_with` / `contains` | 5,000 | 6.35 / 8.72 ms | 7.09 / 8.73 ms | +11.7 / +0.1 % | 2 |
| `count_query(order, ship_state=CA)` | 9,000 | 1.04 ms | 1.03 ms | −1.0 % | 1 |
| `count_query(order)` unbounded | 9,000 | 4.14 ms | 4.29 ms | +3.6 % | 1 |
| `bounded_count_query(cap=3000)` | 9,000 | 2.10 ms | 2.18 ms | +3.8 % | 1 |
| `bounded_count_query(cap=18000)` — above the type | 9,000 | 5.20 ms | 5.53 ms | +6.3 % | 1 |
| Inertia `/admin/records/order` | 9,000 | 41.16 ms | 44.41 ms | +7.9 % | 8 |

The HTTP-driven rows carry a consistent few per cent that the pure-SQL rows do
not (`count_query` alone is −1.0 %), which would be a per-request constant of
under a millisecond if it were real. **It is not attributable to any commit.**
Bisecting the five Phase 5 feature commits — `4da519f` (import/export),
`7f55187` (i18n backend), `8f1963b` (unique among non-siblings), `f655822`
(aggregates and reduce), `da162c6` (collections) — two runs each on the same
file, finds no step at any of them:

| operation | `cd82e9a` | `4da519f` | `7f55187` | `8f1963b` | `f655822` | `da162c6` |
|---|---|---|---|---|---|---|
| text `eq` (city), 1,000 | 8.87 | 8.73 | 8.72 | 10.43 | 9.75 | 9.16 |
| ref `eq` (customer), 9,000 | 9.47 | 9.69 | 9.36 | 10.25 | 9.99 | 9.25 |
| select `eq`, 9,000 | 13.91 | 14.04 | 15.58 | 15.24 | 14.92 | 15.81 |
| list page 1, 9,000 | 18.00 | 18.68 | 19.38 | 18.51 | 18.88 | 20.83 |
| one record by uuid | 4.94 | 4.92 | 5.50 | 5.23 | 6.00 | 5.13 |
| Inertia list view | 43.08 | 41.14 | 41.04 | 44.10 | 46.40 | 44.08 |
| `count_query` alone | 0.92 | 0.86 | 0.93 | 1.01 | 0.91 | 0.92 |

Statement counts across that whole row of commits: 3 for a list page, 2 for
`?total=false` and for a single record, 8 for the Inertia view, 1 for a count.
Unchanged, every one.

### Where the >15 % rows actually come from

Against `d5f4e0f` — the instructed baseline, which predates Phase **4** as well
as Phase 5 — eighteen rows move by more than 15 %. Every one of them was
bisected to a commit by running the *same* `test_read_path.py` (byte-identical
at every commit in the range) at each of `ce02637`, `7e2948b`, `5b6fb36`,
`e8c1ff8` and `cd82e9a`:

| operation | `d5f4e0f` | `5b6fb36` | `cd82e9a` | `da162c6` | verdict |
|---|---|---|---|---|---|
| Inertia `/admin/records/order` | 32.11 ms, **5 stmts** | 38.86 ms, **8 stmts** | 41.05 ms | 44.41 ms | **`5b6fb36`** — Phase 4 §9's batched relation expansion, one query per relation field. Already documented; the count is the finding. |
| text `eq` (city) | 6.55 ms | 7.21 ms | **9.48 ms** | 10.67 ms | **`cd82e9a`** |
| ref `eq` (customer) | 7.10 ms | 7.44 ms | **9.02 ms** | 10.79 ms | **`cd82e9a`** |
| select `eq` (ship_state) | 11.78 ms | 13.44 ms | **14.72 ms** | 16.27 ms | **`cd82e9a`** |
| list page 1 | 14.78 ms | 15.13 ms | **18.32 ms** | 19.54 ms | **`cd82e9a`** |
| the other ten filter/list rows | | | | +18…+37 % | **`cd82e9a`**, same shape |

`cd82e9a` is F4 + F11, and the §"What the list page costs now that it does all
this" table above already prices them: the bounded count costs an extra
aggregate on a type below the ceiling, and the page now selects its sort values
and encodes a cursor for its last row. It is a **constant ~2–3 ms per API
request** — the same 3.2 ms on a 1,000-record type as on a 9,000-record one,
while `count_query` alone does not move at all — so it is the request, not the
SQL. A caller that sends `?total=false` gets most of it back.

Two rows move the other way, and both are F5 at `cd82e9a`: sorting 9,000 orders
by `-updated_at` went **43.47 → 19.84 ms (−54 %)** and the single-valued index
sorts (`placed_at`, `customer`) went 33–39 → 28–32 ms.

**Nothing in the Phase 5 feature span is responsible for any row over 15 %.**

### The cost of each feature, switched on one at a time

Each feature is priced **against itself**, off and on in one process against
copies of the same file, rather than against a baseline tree — which is the
only way to separate "what this feature costs" from the drift above. These
rows are one run each: they are dominated by statement counts and by
throughput over thousands of records, not by the few-millisecond differences
the tables above had to resolve.

#### A reduce index (§5.2)

`records_index_reduce` is maintained by delta inside the write. With no spec
registered the writer iterates an empty tuple and issues nothing at all; with
one registered the cost is exactly one `UPDATE`.

| | statements | p50 |
|---|---|---|
| `create_record(company)`, **no spec registered** | **13** | 14.92 ms |
| `create_record(company)`, one spec, steady state | **14** (+1) | 16.94 ms |
| `create_record(company)`, one spec, a group's **first sight** | **17** (+4) | — |
| `update_record`, one spec, the edit does not move the group | **20** (+0) | 17.88 ms |

The +4 is `UPDATE` (matching no row) → `SAVEPOINT` → `INSERT` → `RELEASE`: the
`UPDATE` matching nothing is the only signal that a group has never been
counted, and the savepoint is what keeps a racing writer's `IntegrityError`
from killing the transaction. A type pays it once per group, ever. The +0 row
is the one worth keeping: a spec whose contribution is unchanged tells the
database nothing, so an ordinary edit on a type carrying a reduce index costs
what it always cost. All three are asserted, not just printed.

Rebuilding the whole fold: `rebuild_type(order, orders_per_state)` over 9,000
records into 50 groups took **398 ms — 22,612 rec/s**, one `INSERT … SELECT …
GROUP BY` per spec.

#### The live aggregate, and reading the maintained one (§5.1)

`GET /types/{key}/records/aggregate` is **two statements on any type** — the
type load and one `GROUP BY` — and the suite asserts that the count does not
vary between the 9,000-record `order` and the 3,000-record `product`.

| aggregate over 9,000 orders (3,000 products for `tags`) | p50 | statements |
|---|---|---|
| `group_by=ship_state` (select) | 27.81 ms | 2 |
| `group_by=ship_state&metric=sum:total` | 36.00 ms | 2 |
| `group_by=ship_state&metric=max:placed_at` | 39.76 ms | 2 |
| `group_by=customer` (relation) | 41.50 ms | 2 |
| `group_by=status` (fixed column, no join) | 10.88 ms | 2 |
| `group_by=tags` (multiselect, 3,000 products) | 13.73 ms | 2 |
| `group_by=ship_state` + one datetime filter | 18.73 ms | 2 |
| **`?reduce=orders_per_state`** — the same fold, maintained | **6.81 ms** | 3 |

The last row is the entire argument for a reduce index, and the endpoint serves
both readings so a caller can take it: the live `GROUP BY` is **O(rows folded)**
and reads `records_index_text` through its lookup index; the stored one is
**O(groups)** and reads 50 rows out of `records_index_reduce`. 27.83 → 6.81 ms
at 9,000 records, and the gap widens with the type. The measurement asserts the
two return the same groups with the same counts, which is also how drift in a
maintained aggregate is noticed by the thing that reads it.

Without the request around it, the `GROUP BY` alone is **one statement**:
22.21 ms for a count over 9,000, 30.84 ms with `sum:total`, and **2.34 ms** once
a filter narrows it — the aggregate is proportional to what it folds, not to
the type.

#### A second content locale (§4)

| | p50 | statements |
|---|---|---|
| `GET /company/records`, **one** content locale | 13.46 ms | 3 |
| `GET /company/records`, two locales, all locales | 16.43 ms | 3 |
| `GET /company/records?locale=en` | 13.24 ms | 3 |
| `GET /company/records?locale=de` | 13.99 ms | 3 |
| public list, **one** content locale | 14.11 ms | **4** → **3** (S1) |
| public list, two locales, default locale | 17.15 ms | **4** |
| public list `?locale=de` | 16.45 ms | **4** |
| `ensure_slug_free(company, locale=en / de)` | 0.51 / 0.52 ms | 1 |
| `published_siblings(company, 25 records)` | 1.37 ms | 1 |
| `create_translation` ×500 over 1,000 companies | 6.52 s — **77 rec/s** | — |

`?locale=` is free, and that is the design working: locale is a fixed column,
so filtering on it is a predicate on `records_record` and not a join —
`test_a_second_locale_on_the_list_and_the_public_page` asserts that the
filtered list costs exactly what the unfiltered one costs. The per-locale slug
claim is one indexed statement, unchanged from F2's shape with a locale column
added to the predicate. The sibling lookup for a whole page is one query keyed
by `translation_group`, never one per row, and costs 1.37 ms for 25 records.

**The public list was four statements where the admin list is three, on a host
that publishes in one language.** That was the one place Phase 5's
"inert when unused" promise was not kept, and it is §S1 above: on one content
locale the sibling batch is not issued at all, so the public list is three
statements and the public record read is two. The rows in this table are the
two-locale ones, where the batch is real work and costs what it says.

#### A type in a collection (§6)

Measured in a subprocess (`tests/perf/_collection_worker.py`), because
`declare_collection` is a process-global side effect that has to happen before
any app is built — declaring one inside this suite would add eight tables to
the file every other measurement runs against. Two types with identical fields,
one global and one in a declared collection, 2,000 records each:

| operation | global | collection | statements |
|---|---|---|---|
| `create_record` | 9.97 ms | 9.76 ms | 8 both |
| list page of 25 | 1.20 ms | 1.17 ms | 1 both |
| list, number `gte` filter | 2.25 ms | 2.22 ms | 1 both |
| list, sort by an indexed text field | 3.56 ms | 3.39 ms | 1 both |
| seeding 2,000 records | 13.2 s (151 rec/s) | 13.7 s (146 rec/s) | — |

Boring, which is the result: the tables are built by the same factory, so
`test_a_collection_type_costs_what_a_global_type_costs` asserts the statement
counts are equal *and* the query plans are equal line for line once the
`records_c_<name>_` prefix is stripped.

The one thing a collection *did* cost is **the referrers walk, and it cost it
to every host that declared one whether or not any type lived in it**:

| declared collections | statements per `referrers()` | after S5 |
|---|---|---|
| 1 | 2 | **1** |
| 2 | 3 | **1** |

One read per declared table set, by construction: a `UNION` would merge ids
that mean different rows, because two collections number their records
independently (§6.6), so the walk asks each set in turn and keeps each set's
ids with that set's class. What it no longer does is ask a set that cannot hold
a referrer — §S5 above. Every `restrict` delete and every referrers panel pays
one read per set that holds a type with a relation to the record's type, plus
the one schema query that says which those are.

#### Import and export (§2)

Whole-type, `order`, 9,000 records:

| | wall | rate | peak memory | output |
|---|---|---|---|---|
| export as JSON (streamed) | 1.65 s | **5,448 rows/s** | 5.3 MB | 6.0 MB |
| export as CSV (streamed) | 1.74 s | **5,161 rows/s** | 4.9 MB | 3.3 MB |
| import the JSON back, `upsert` | 11.03 s | **816 rows/s** | — | 9,000/9,000 **skipped** (now **917 rows/s**, §S4) |
| import with a bad row at 9,000 of 9,000, `on_error=abort` | 11.46 s | — | — | refused, **nothing written** (now 9.2 s, §S4) |

The two peaks are within 10 % of each other while the two files differ by
nearly 2×, which is the memory claim: `walk_records` is keyset by `id` and
`expunge_all`s between batches, so what is live is a batch of records and one
chunk of output, not the type and not the file. (The first attempt at this
number said 974 rows/s and 12.6 MB — `tracemalloc` was running during the timed
pass and the test's own `"".join` of every chunk was being counted as the
exporter's memory. The measurement now makes two passes, one timed and one
under `tracemalloc` that throws every chunk away.)

The round trip is idempotent and the report says so: **every one of the 9,000
rows was skipped**, because each matched an existing record by `uuid` and
compared equal. `abort` with the failure in the last row is the worst case by
construction — a run that stops at its first bad row cannot stop earlier than
the end when the bad row *is* the end — and it costs the validation pass and
then refuses with the record count untouched. Both numbers are the ones S4
brought down; the after figures are in that section.

#### The deferred preview, and saving after one (§1, F10)

| `order.gift` becomes required, 9,000 records | |
|---|---|
| `POST /schema/preview` synchronous — time to the response | 1,624 ms |
| `POST /schema/preview` deferred — time to the `202` | **6.36 ms** |
| the job's whole run, scan included | 1,509 ms |
| `PUT /types/order` with no reusable report (inline scan) | 1,417 ms |
| `PUT /types/order` reusing a completed preview | **8.43 ms** |

The last pair is the half of F10 that had never been measured: an apply that
can take a finished job's report is **168× faster** than one that cannot,
because the saved work is the entire dry run.
`preview_job_ttl_seconds = 0` is what every install that wants the scan
unconditionally sets, and that is exactly the row above it.

#### The bounded count at the cap (§1, F4)

| `bounded_count_query(order, …)` | 9,000 orders |
|---|---|
| `cap = 3000` (below the type) | 2.18 ms |
| `cap = 8999` (one below) | 5.67 ms |
| `cap = 9000` (**at** the cap) | 6.07 ms |
| `cap = 18000` (above the type) | 5.53 ms |
| unbounded | 4.29 ms |

The bound reads `cap + 1` rows, so at the cap it is the whole type plus the
probe row that tells the caller there is more — the most expensive place the
ceiling can sit, and the place a host tuning `max_count` naturally puts it.
Below the cap it is cheaper than the unbounded count; at or above it, it is the
unbounded count plus a trivial outer aggregate. `test_the_bound_at_the_cap`
asserts the returned number is `min(n, cap + 1)`, which is what the
`total_capped` flag is computed from.

### Three measurements in this suite were wrong, and are fixed

Found while re-running, and worth writing down because each produced a
plausible number that meant something else:

* **`reindex store (batch=100 / 500 / 2000)` measured three different
  operations.** The loop flipped `indexed` on `store.street` each time round,
  so batch=100 *added* a field's index rows, batch=500 *removed* them and
  batch=2000 added them again — the batch size was confounded with the
  direction of the toggle, which is fatal for a row whose only purpose is
  "bigger is better". Each iteration now restores the state it found in an
  untimed pass first. With that fixed the three are monotone again and mean
  what they say: **751 ms (2,660 rec/s) / 511 ms (3,914) / 482 ms (4,148)** for
  2,000 records.
* **The export's peak memory was the test's own buffer**, as described above.
* **`measure()` explained the wrong statement for an aggregate.** It takes the
  plan of the *longest* statement, which is right for a list page (the filtered
  `SELECT` is also the longest text) and wrong for an aggregate, where the
  `GROUP BY` is short and the type load's column list is long — so the plan
  cell described the type load and `assert not plan_scans_records(plan)` passed
  vacuously. `measure(..., plan_of="GROUP BY")` names the statement to explain.

And one that is fixed only by repetition: **`_orphaned.count_conflicts` cannot
be measured once.** The same commit, the same file, the same 2,000-record walk
gave **50 ms** in one batch of runs and **208 ms** in another — a 4× spread with
no code between them. It is read-only, so it now repeats;
`_orphaned.discard` and `type revision rollback` write, so they remain single
samples and should not be compared across runs. That is what made an earlier
draft of this section report a 63 % "improvement" in `count_conflicts` that did
not exist.

### Schema operations, all three trees, the same file

Median of three, with the corrected reindex measurement:

| operation | `d5f4e0f` | `cd82e9a` | `da162c6` |
|---|---|---|---|
| `dry_run(order, gift required)`, 9,000 records | 9,215 ms | 9,309 ms | 9,333 ms |
| `schema apply(force, restrictive)` | 1,626 ms | 1,607 ms | 1,584 ms |
| `reindex store`, batch 100 / 500 / 2000 | 999 / 633 / 553 ms | 961 / 617 / 530 ms | 965 / 683 / 485 ms |
| `display_field` change, whole-type rebuild | 1,158 ms | 1,017 ms | 1,193 ms |
| `_orphaned.discard(store.hours)` | 218 ms | 191 ms | 211 ms |
| type revision rollback | 13.5 ms | 13.9 ms | 24.1 ms |

Every row of the rebuild and the dry run is within the single-sample spread
those measurements have; the dry run, which is the one row here with a stable
number, is **+1.3 % over the whole range**.

## Still open

**Nothing with a number.** The original study's eleven findings and the Phase 5
round's five are all in §Fixed above. What is left is work on the *instrument*
and two facts about the module that are trades rather than bugs.

**The write path, the schema operations and the `FOR UPDATE` row lock are still
unverified on Postgres.** `perf_db_copy` copies a SQLite *file*, so every test
that mutates its database skips on `RECORDS_PERF_URL` and says so. Giving it a
Postgres equivalent — a template database and `CREATE DATABASE … TEMPLATE` — is
the next thing this suite needs, and it is what would let the S2 write rows
above (three more btree inserts per record) be measured on the backend whose
planner the indexes were added for. `_create_missing_indexes` is already
backend-independent, which is half of it: a database seeded before a revision
added an index picks it up on the next run under either dialect.

**Import is CPU in Pydantic, and stays there.** S4 removed the second schema
pass; what a no-op import still pays is parsing every row and validating it
against the compiled model, which is the half that makes an import safe. A
faster answer would mean not validating, and that is not on offer.

**An index added by a revision needs `ANALYZE` on SQLite, and only this
revision does it.** §S2 explains why — an index with no `sqlite_stat1` row is
assumed to be very selective, so on a half-analysed database it wins lookups it
should lose. `c4a17b9de0f2` runs `ANALYZE` after creating its indexes and the
perf suite's index recovery does the same, but nothing *enforces* it: the next
revision that adds an index to `records_record` has to remember. A `doctor`
check for "an index on a records table with no statistics row" would be the way
to stop remembering.

**A row-value cursor is only available to a non-nullable single-term sort.**
`NULLS LAST` is not an order a row value can express, and every sort on an
indexed field wears it because the field is reached by a `LEFT OUTER JOIN`. The
deep-page case the product actually issues — `?sort=-placed_at&after=…` — is
therefore still a post-join `Filter` on Postgres (§S3). Making it a seek would
mean changing how a missing index row sorts, which is a contract, not a plan.

### Deliberate trades, unchanged

Both from the F-round and both still true: `ix_records_record_type_position_id`
slows the default two-term list ordering on a type whose `position` is uniform
(F5), and the bounded count costs an extra aggregate on a type below
`max_count` (F4).

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

The rows above were taken at `cd82e9a`, and the Phase 5 section shows the
whole read and write path is still inside the instrument's drift of them. What
Phase 5 *added* has no earlier number to sit beside, so it is listed
separately — same dataset, same run:

| operation | type size | p50 |
|---|---|---|
| `GET …/records/aggregate?group_by=…`, live `GROUP BY` (**2 statements**) | 9,000 | 10.9–41.5 ms |
| the same `?group_by=` with a filter | 9,000 | 18.7 ms |
| `GET …/records/aggregate?reduce=…`, maintained (3 statements) | 9,000 | **6.8 ms** |
| `aggregate_query` alone, count / `sum:` / filtered (**1 statement**) | 9,000 | 22.2 / 30.8 / 2.3 ms |
| `rebuild_type` for one reduce spec | 9,000 | 398 ms — 22,600 rec/s |
| `create_record` with one reduce spec (14 statements, 17 on a group's first sight) | 20,000 total | 16.9 ms |
| public list, 1 / 2 content locales (**3 / 4 statements**, S1) | 1,000 | 9.8 / 17.2 ms |
| admin list with `?locale=` (3 statements, same as without) | 1,500 | 13.2–14.4 ms |
| `ensure_slug_free(type, locale)` (1 statement) | 1,000 | 0.5 ms |
| `published_siblings` for a 25-record page (1 statement, **0 on one locale**) | 1,000 | 1.4 ms |
| `create_translation` | — | 13 ms — 77 rec/s |
| export whole type, JSON / CSV, streamed | 9,000 | 1.65 / 1.74 s — 5,448 / 5,161 rows/s, peak ~5 MB |
| import an unchanged export, `upsert` (every row skipped) | 9,000 | 9.8 s — **917 rows/s** (S4) |
| import, `on_error=abort`, bad row last | 9,000 | 9.2 s to refuse, nothing written (S4) |
| `PUT /types/{key}` reusing a completed preview / scanning inline | 9,000 | **8.4 ms** / 1,417 ms |
| a collection type against the same type global (create / list / filter / sort) | 2,000 each | identical, modulo the table prefix |
| `referrers()`, per **declared** collection (S5) | — | +0 statements |

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
* **A reduce spec nobody registered costs nothing at all** — every function in
  `index/reduce.py` returns after a `for` over an empty tuple, and the perf
  suite fails if a create touches `records_index_reduce` on such a host.
* **A collection nobody declared costs nothing either**: `tables_for` answers
  with the global set and the metadata holds the Phase 4 eleven tables. A
  collection that *is* declared reads the same: its plans are compared with
  the global type's line for line, with the table prefix stripped and the
  interchangeable `(type_id, <fixed column>, id)` index names normalised —
  those are equivalent by construction and SQLite picks between them on
  statistics it does not have.
* `?locale=` is a fixed-column predicate, so filtering a list by language is
  free: same statement count, same plan, same milliseconds as not filtering.
* The export streams. Two formats whose files differ by nearly 2× peak within
  10% of each other, because what is live is a batch of records and one chunk
  of output.

## On Postgres — measured, at last

Every previous round of this study ended with "no Postgres binary was
available" and a list of expectations. **PostgreSQL 16.13 was available this
time** (a local cluster, `C.UTF-8`, default `shared_buffers` raised to 256 MB),
and the suite grew a way to use it: `RECORDS_PERF_URL=postgresql+asyncpg://…`
points `perf_db` at a database instead of a SQLite file, and
`_bench.explain` issues `EXPLAIN` rather than `EXPLAIN QUERY PLAN` when the
dialect is not SQLite. `plan_scans_records` learned Postgres's spelling of a
full scan (`Seq Scan on records_record`) and `plan_temp_btree` its spelling of
a sorter (`Sort`). `perf_db_copy` copies a *file*, so the tests that mutate
their database skip there and say so; the read path, the pagination and the
aggregate — which is where every unverified finding was — run unchanged.

The same 20,000-record dataset was seeded into it and the read path was run
twice: once immediately after the bulk load with **no statistics at all**, and
once after `ANALYZE`. That pair is the one the earlier doc asked for, because
"immediately after a restore or a bulk load" is exactly the state a migration
leaves.

**All 30 read-path and pagination measurements pass on Postgres, with and
without statistics, and no plan anywhere reads `records_record` sequentially.**

### F1, the semi-join — confirmed, and better than it is on SQLite

```
GET order list, datetime range gte (placed_at), 9,000 orders
  Hash Semi Join  (cost=281.75..1196.50 rows=2051)
    Hash Cond: (records_record.id = records_index_datetime.record_id)
    ->  Index Scan using ix_records_record_type_id on records_record
          Index Cond: (type_id = 5)   Filter: (is_deleted IS FALSE)
    ->  Seq Scan on records_index_datetime
          Filter: ((value >= '2024-01-01…') AND (type_id = 5) AND (field_key = 'placed_at'))

GET order list, 3-filter AND
  Nested Loop Semi Join
    ->  Nested Loop Semi Join
          ->  Nested Loop
                ->  HashAggregate (Group Key: records_index_text.record_id)
                      ->  Index Scan using ix_records_index_text_lookup on records_index_text
                            Index Cond: ((type_id = 5) AND (field_key = 'ship_state') AND (value = 'CA'))
                ->  Index Scan using pk_records_record on records_record
                      Index Cond: (id = records_index_text.record_id)
          ->  Index Scan using ix_records_index_number_record on records_index_number
    ->  Index Scan using ix_records_index_datetime_record on records_index_datetime
```

`IN (SELECT record_id FROM idx WHERE …)` becomes a real `Hash Semi Join` or
`Nested Loop Semi Join`: the subquery is evaluated once and the outer table is
reached by primary key, which is exactly the shape F1 was rewritten to produce.
The `Seq Scan` on `records_index_datetime` in the first plan is the planner
being right — 4,557 of 9,000 rows match that range, so a scan beats an index —
and it is a scan of the *index* table, proportional to matches, not of the
type. **`ANALYZE` changed no plan**; the 24 filter and sort rows moved by −18 %
to +14 % between the two runs with no structural difference, which is this
machine's noise and not the planner changing its mind. The pathological ratios
F1 found on statistics-free SQLite do not reproduce here in either state.

### F5, the direct-join sort — the SQLite-specific traps do not reproduce

```
GET order list, sort placed_at (single-valued datetime), 9,000 orders   17.14 ms
  Limit → Sort (Sort Key: records_index_datetime_1.value, records_record.id)
    →  Hash Right Join (Hash Cond: records_index_datetime_1.record_id = records_record.id)
         →  Seq Scan on records_index_datetime  Filter: (field_key = 'placed_at')
         →  Index Scan using ix_records_record_type_id on records_record
```

Same shape for `customer` (18.91 ms, over `records_index_ref`). The `MIN`
aggregate survives only for the multiselect, as designed:

```
GET product list, sort tags (multiselect), 3,000 products                7.87 ms
  Limit → Sort → Hash Left Join → HashAggregate (Group Key: record_id)
          →  Bitmap Index Scan on ix_records_index_text_lookup
```

And the two planner choices the SQLite study flagged as SQLite's own:

* **The `type_id`-in-the-`ON`-clause trap does not exist here.** The join is on
  `record_id` and `field_key` and Postgres hash-joins it; nothing re-scans a
  `(type_id, field_key)` range per row.
* **The admin list's default order does not prefer the position index.**
  `ORDER BY position, updated_at DESC NULLS LAST, id` is answered by an index
  scan on `ix_records_record_type_id` plus one `Sort`, at 6.33 ms — Postgres
  makes neither of the two choices SQLite makes, which is what the earlier
  section asked someone to verify rather than assume.

The fixed-column indexes of F5 do serve Postgres, but **only in one
direction**:

| sort, 9,000 orders | p50 | plan |
|---|---|---|
| `position` (`NOT NULL`) | 1.09 ms | `Index Scan using ix_records_record_type_position_id`, stops after 25 |
| `-position` | 1.15 ms | `Index Scan Backward using ix_records_record_type_position_id`, stops after 25 |
| `created_at` (`NOT NULL`) | 1.52 ms | `Index Scan using ix_records_record_type_created_id`, stops after 25 |
| `published_at` (nullable) | 4.84 ms | `Incremental Sort` over `ix_records_record_published_at` |
| `-published_at` (nullable) | 6.16 ms | **full `Sort` of 9,000 rows** |
| `-updated_at` (nullable) | 7.07 ms | **full `Sort` of 9,000 rows** |

The nullable descending case was a real finding; it is fixed, and §S2 has the
plans it now produces.

### F11, the keyset cursor — wins, but not by a seek

```
GET order list page 200 by ?after=, sort=-placed_at              26.47 ms, 2 statements
  Limit → Sort (Sort Key: records_index_datetime_1.value DESC NULLS LAST, records_record.id)
    →  Hash Right Join
         Filter: ((value < '2023-09-18…') OR (value IS NULL)
                  OR ((value = '2023-09-18…') AND (records_record.id > 19298)))
         →  Seq Scan on records_index_datetime  Filter: (field_key = 'placed_at')
         →  Index Scan using ix_records_record_type_id on records_record

GET order list page 200 by ?page= (OFFSET 4975)                  41.05 ms, 3 statements
```

The cursor still beats `OFFSET` by 1.6×, and it beats it for the reason that
matters — it does not produce and discard 4,975 rows — but the keyset predicate
lands in the join's `Filter`, after the join, so it narrows nothing before the
sort. The two return byte-identical pages, which the measurement asserts.

**This row is the one case S3 leaves alone, and deliberately**: `placed_at` is
an indexed field reached by `LEFT OUTER JOIN`, so its sort wears `NULLS LAST`
and a row-value comparison cannot express it. A sort on a *non-nullable* fixed
column now does seek — see §S3 for the plan.

### The rest of it

* `starts_with` is a range on Postgres too: `Index Cond: ((type_id = 2) AND
  (display_title >= 'Smith') AND (display_title < 'Smiti'))` on
  `ix_records_record_type_title_id`, 7.44 ms against `contains`'s 14.26 ms
  sequential filter. This cluster is `C.UTF-8`; under a linguistic collation
  the index is built in that collation and the range still uses it, but what
  the range *means* changes — the existing caveat about case sensitivity
  stands unaltered.
* The bounded count of F4 compiles to the same `Aggregate → Subquery Scan →
  Limit` shape and the soft-delete filter appears **inside** the `Limit`
  (`Filter: (anon_1.is_deleted IS FALSE)` on the subquery scan and the inner
  scan alike), which is the property F4 goes to some length to keep. 1.50 ms
  at `cap = 3000`.
* `analyze_tables` remains a deliberate no-op here (`dialect.name != "sqlite"`),
  and the two runs above are why that is right: autovacuum's statistics changed
  nothing the module cares about, in either direction.
* Absolute numbers are 1.3–1.8× SQLite's on this machine across the board — an
  out-of-process database over a socket against an in-process file. That ratio
  is the harness, not the module, and nothing should be read into it.

~~**Still not verified on Postgres:** the write path, the schema operations and
`tests/test_unique_concurrency.py`'s `FOR UPDATE` row lock, because
`perf_db_copy` has no Postgres equivalent and those tests mutate. Giving it one
(a template database and `CREATE DATABASE … TEMPLATE`) is the next thing this
suite needs.~~ — done, 2026-09-21; see below.

### Postgres — the write path, concurrency and the rest of the suite

**The whole suite now runs on Postgres**, and so do the 927 unit tests and the
109 Playwright specs. Full evidence, including three migration bugs that made
a Postgres install impossible from an empty database, is in
[`postgres-2026-09-21.md`](postgres-2026-09-21.md). `perf_db_copy` got its
template database, so the 19 measurements that used to skip — schema
operations, import and export, the reindex, content i18n, the reduce index —
have numbers here for the first time.

`RECORDS_PERF_N=20000`, `REPS=20`, PostgreSQL 16.13 against SQLite 3.45 on the
same machine in the same session. **Ratio is Postgres ÷ SQLite; under 1.00 is
faster.**

| operation | SQLite | Postgres | ratio |
|---|---|---|---|
| `create_record` / with a `unique` field | 11.91 / 14.02 ms | **8.60 / 10.04 ms** | 0.72× |
| `update_record`, no indexed change / `price` | 18.06 / 20.01 ms | **13.22 / 13.18 ms** | 0.73× / 0.66× |
| trash → restore → trash → purge | 46.18 ms | **30.62 ms** | 0.66× |
| list page 1, unfiltered | 20.21 ms | 17.37 ms | 0.86× |
| **page 200 by `?page=` (`OFFSET`)** | 78.40 ms | **39.21 ms** | **0.50×** |
| page 200 by `?after=` | 24.95 ms | 26.54 ms | 1.06× |
| **three ANDed filters** | 49.24 ms | **16.88 ms** | **0.34×** |
| single filters (text / select / number / ref) | — | — | 0.88–1.12× |
| sorts (text, number, datetime, ref, fixed column) | — | — | 0.77–1.17× |
| `count_query` unbounded | 5.09 ms | **2.08 ms** | 0.41× |
| live `GROUP BY` aggregate | 26.44 ms | **15.87 ms** | 0.60× |
| import, `upsert`, unchanged export | 10.58 s (847 rows/s) | **8.56 s (1,047 rows/s)** | 0.81× |
| export JSON / CSV, streamed | 1.53 / 1.65 s | 1.50 / 1.65 s | 1.00× |
| `create_translation` | 71 rec/s | **103 rec/s** | 0.68× |
| `reindex`, batch = 500 | 433.74 ms | **672.09 ms** | **1.55×** |
| `display_field` change, whole-type rebuild | 932.40 ms | **1309.39 ms** | **1.40×** |
| `_orphaned.count_conflicts` / `.discard` | 44 / 258 ms | 69 / 333 ms | 1.56× / 1.29× |

Three things are worth carrying away.

**The write path costs fewer statements on Postgres, and "statement counts
travel" is wrong for it.** A create is **10 statements on Postgres and 13 on
SQLite**, and the gap widens with the number of indexed fields: `write_index`
batches its index rows into one `INSERT` per *kind table* on Postgres and one
per *row* on SQLite. Measured directly, on a type with eight indexed `text`
fields, a create is 14 statements on SQLite and still 7 on Postgres. **The
"13 statements per create" figure published above is SQLite's, for the demo
`company` type.** Every other statement count in this document is identical on
both backends.

**The per-type lock holds.** `tests/test_postgres_lock.py` fires twenty
concurrent `create_record` calls carrying one `unique` value from twenty
separate sessions: one succeeds, nineteen get the 409, one row is stored, no
`IntegrityError` escapes and nothing deadlocks. Same for concurrent slug
claims, and a `update_type` racing twenty creates leaves every record stamped
with a `schema_version` the type has actually had. This is the first execution
of `lock_type`'s `SELECT … FOR UPDATE` branch —
`tests/test_unique_concurrency.py` races on a SQLite file and reaches the
other one.

**Bulk index rewrites are the one place Postgres is slower** (1.3–1.55×). At
batch = 100 the two are level, so it is not per-statement latency; it is the
`DELETE` + re-`INSERT` of index rows costing more against real MVCC than
against a file. 2,965 rec/s at batch 500 is still far inside
`reindex_stale_after_seconds`, and the rebuild is a background job.

Two corrections to the section above, both from measuring rather than
predicting:

* "Absolute numbers are 1.3–1.8× SQLite's across the board" does not hold on
  this machine. Across 122 measurements Postgres is at parity or faster for
  everything except the bulk rewrites — the earlier ratio was a property of
  that run's harness, as that bullet itself suspected.
* "No plan anywhere reads `records_record` sequentially" was said of the read
  path. The **bounded count** does, when `cap` is well below the type size:
  Postgres takes a `Seq Scan` stopped early by the `LIMIT` and is *faster* for
  it (1.49 ms vs 2.57 ms). The property F4 actually cares about — the
  soft-delete filter staying inside the `Limit` — holds.
