# Offline migration SQL

Generated from the repo root with

```bash
SM_DATABASE_URL=postgresql+asyncpg://…/regen \
  .venv/bin/alembic -c host/alembic.ini upgrade base:heads --sql
```

`postgres-base-to-heads.sql` is the whole history — 23 revisions, 43 tables,
124 indexes, 8 enum types, 1,006 lines — as one transaction, for review or for an
operator who applies DDL by hand. It is regenerated, not edited.

Two assumptions are baked into it by `b1f4a72c9d30`, which backfills data and
therefore cannot read the database it is written for. Both are spelled out in
that revision's docstring: the default content locale is emitted as the literal
`'en'`, and `pagebuilder_pages.translation_group` is backfilled by one
set-based `UPDATE` deriving `'p' || id` rather than a `uuid4` per row. An
install whose default content locale is not `en` has to edit that literal
before running the script. Online runs take neither path.

## There is no SQLite equivalent, and it is not the repo's doing

`alembic upgrade base:heads --sql` on SQLite stops at `af06f6ea093e` with

```
This operation cannot proceed in --sql mode; batch mode with dialect sqlite
requires a live database connection with which to reflect the table
"pagebuilder_pages".
```

SQLite has no `ALTER COLUMN`, so every `alter_column` / `drop_column` goes
through Alembic's batch mode, which rebuilds the table — and to write that
`CREATE TABLE` without a database it needs the table handed to it as a complete
`copy_from=` `Table`. Six revisions use batch mode across 26 call sites, each of
which would have to carry a hand-written copy of that table *as it stood at that
point in history*. That is a far larger and more fragile change than the offline
script is worth, so it has not been made; a SQLite host migrates online.

The same limitation stops any sub-range that contains a batch revision,
including the records-only range, which reaches `a7c3e1d4b920` before hitting
`records_record`.
