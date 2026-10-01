# Records documentation

`simple_module_records` lets an administrator define **Record Types** — named
schemas, each an ordered list of typed fields — from the admin UI, and manage
their **Records** without a developer writing a table or a migration for each
one. Records are stored as JSON documents; declared fields are projected into
typed SQL index tables so they stay queryable.

Start with the document that matches what you are trying to do.

## Who should read what

| You are | Read |
|---|---|
| An administrator defining types and managing records | [user-guide.md](user-guide.md) |
| A developer calling the module over HTTP | [api-reference.md](api-reference.md) |
| An operator installing, configuring or running it | [operations.md](operations.md) |
| A developer extending or modifying the module | [architecture.md](architecture.md) |
| Anyone wondering what it costs at scale | [performance.md](performance.md) |

### [user-guide.md](user-guide.md) — for administrators

Every admin screen in the order a person meets them: the Records hub, the type
editor (each field kind and what its options mean; `Indexed`, `Unique`,
`Required`; display and slug fields; Public, Translatable, Show in sidebar,
Allowed roles, Collection), the record list (columns, filters, sorting, paging,
trash, export and import), the record editor (status, language, slug, position,
relations, referrers, history, the conflict panel, translations) and what
happens when you change a schema that already holds records. Uses the exact UI
labels.

### [api-reference.md](api-reference.md) — for integrators

Every endpoint under `/api/records` and under the anonymous read prefix: method,
path, permission, query grammar, request and response shapes by contract class,
and the full error table. Also the CSV and JSON import/export formats, the
aggregate endpoint, preview jobs, and how the public API differs from the admin
one. Examples are real request/response pairs.

### [operations.md](operations.md) — for operators

Install and entry point, the nine Alembic revisions and the `records@base`
caveat, every setting with its default and whether it needs a restart, the CLI
(`seed`, `reindex`, `reindex --verify`, `export`, `import`), the health check
and what degrades `/health/ready`, the single-process assumptions that are
deployment constraints, SQLite versus PostgreSQL, backup and restore, and the
upstream framework issues this module works around.

### [architecture.md](architecture.md) — for contributors

The document/index split, the six index tables and the semi-join, how a schema
change is classified and applied, the services layer's rules, the extension
points (index providers, virtual fields, collections, reduce specs), where the
wire contracts live, and the test harness.

### [performance.md](performance.md) — measured behavior

The maintainer's copy of the performance findings: what each fixed finding cost
before and after, what a list page costs now, what each Phase 5 feature costs
when used and when not, and how to run the `perf` suite yourself.

## Reference material

These are point-in-time records, not living documentation. Read them for
evidence and reasoning, not for current behavior — where one disagrees with the
code, the code is right.

| Document | What it is |
|---|---|
| [perf-study-2026-09-19.md](perf-study-2026-09-19.md) | The original performance study at 100,000 records: raw output, query plans, every command, findings F1–F11 |
| [postgres-2026-09-21.md](postgres-2026-09-21.md) | PostgreSQL verification run: the behavior that differs from SQLite |
| [qa-api-2026-09-19.md](qa-api-2026-09-19.md) | QA pass over the JSON API |
| [qa-ui-2026-09-19.md](qa-ui-2026-09-19.md) | QA pass over the admin screens |
| [qa-api-phase5-2026-09-20.md](qa-api-phase5-2026-09-20.md) | QA pass over the Phase 5 API surface (i18n, collections, aggregates, import/export) |
| [qa-ui-phase5-2026-09-20.md](qa-ui-phase5-2026-09-20.md) | QA pass over the Phase 5 screens |
| [review-phase4-2026-09-20.md](review-phase4-2026-09-20.md) | Code review of Phase 4 (relations, expansion, referrers) |

## Design documents

The design docs are where the *reasoning* lives. They are dated and they are
the source of truth for why something is the way it is — not for what it
currently does.

- [`docs/plans/2026-09-19-records-module-design.md`](../../../docs/plans/2026-09-19-records-module-design.md)
  — the original design. The storage model (§4–§5), the closed field-type set
  (§6), the index layer and the "if it is not indexed it is not queryable" rule
  (§7), schema evolution (§8), relations (§9), permissions and the public API
  (§10), settings (§11) and the frontend (§12). Section numbers are cited
  throughout the source.
- [`docs/plans/2026-09-20-records-phase5-design.md`](../../../docs/plans/2026-09-20-records-phase5-design.md)
  — Phase 5: keyset pagination and bounded counts (§1), import/export (§2), the
  pagebuilder widget (§3), content languages (§4), aggregates and reduce
  indexes (§5) and collections (§6).

## Also

- [`../README.md`](../README.md) — the package README: install, usage, and the
  long-form notes on relations, collections, content languages and the index
  extension points.
