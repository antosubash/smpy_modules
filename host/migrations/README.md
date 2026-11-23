# Migrations

Every Alembic revision for this host lives in `versions/`. Modules ship
SQLModel tables only; each consuming host autogenerates its own revisions
against them. Run alembic from the repo root as
`uv run --project host alembic -c host/alembic.ini <command>` (there is no
`alembic.ini` at the root; `host/alembic.ini` resolves `script_location` relative
to itself). `make migrate`, `make migration` and `make downgrade` wrap it; the
`alembic ...` commands below (`merge heads`, `downgrade <module>@base`, `check`)
take the same prefix.

## Rules

**One head.** The history is not linear: two PRs that each add a revision off
the same parent leave two heads once both land. That breaks `make migration`
("Multiple heads are present") and makes `make downgrade` (`-1`) roll back an
arbitrary branch (#107). The fix is an empty `alembic merge heads` revision (see
`52ce60faa542` and `d3a2801784b0`); `scripts/check_migration_heads.py` fails CI
until one exists. `make migrate` runs `upgrade heads`, which would hide a split,
so do not rely on it to notice. Downgrading through a merge point is ambiguous
with `-1`; name the parent.

**A module's first revision carries `branch_labels = ("<module>",)`**, so the
revision can be named (`alembic downgrade <module>@base`). That does **not**
roll back only that module. Autogenerate chains every revision off the current
head, so the labelled revision sits on one shared history and `<module>@base`
walks everything beneath it. Verified: `downgrade records@base` ran 20
downgrades and emptied the database. Removing one module's schema in isolation
needs its tables on a real branch (`down_revision = None`), which nothing here
produces yet. Upstream #333 was closed on 2026-10-07 as a documentation
correction (framework 0.0.36, PR #403): the framework's own docs now say the
label is only a named target, and no behaviour changed.

**Framework tables are this host's to migrate too.** The framework's own
revisions live in its repo's host, not in its wheels. A framework bump therefore
means porting each new revision into this history:

- keep the upstream revision id unchanged, and chain it linearly after the
  current head of the relevant area;
- drop a `branch_labels` that another revision here already carries, because
  Alembic refuses a label used twice;
- run `alembic check` on SQLite **and** on Postgres afterwards.

**The SQLite index check is the framework's.** For an index that mixes columns
and an expression, SQLite reflects `created_at DESC` as a plain column, so
autogenerate would drop and recreate file_storage's `tenant_browse` on every run.
Since 0.0.45 the framework's `make_include_object` skips that false change, so
`env.py` carries no workaround. An index on other columns is still reported.
Alembic skips expression indexes on SQLite altogether, so a missing one is caught
only by the Postgres check.

## Framework revisions ported

Ported revisions keep upstream's ids unchanged. Host-only additions are
`c9e3a5f1b7d2` (the missing initial task-execution table), `9d83e789a5b4` and
`c7a41e9d2b60` (type corrections); the framework ships no matching revisions.

- **0.0.37 / 0.0.38**: `307543b6146a` through `b65e04cf65d7`
  (`307543b6146a` is file_storage upload sessions, `b65e04cf65d7` the leases
  table). Since 0.0.38 SQLModel is unpinned and a bare `datetime` field is
  `timestamptz`, which is why `9d83e789a5b4` retypes the framework's
  `users_refresh_token` columns on Postgres.
- **0.0.40**: bearer tokens are hashed at rest. `a626b1c8d023` deletes every
  `users_access_token` and `users_refresh_token` row, so every session and API
  token is invalidated once on upgrade. Anything that stored a raw token must
  keep the plaintext itself: the table holds only a digest.
- **0.0.41**: added `simple_module_file_storage`, `simple_module_sharing` and
  `simple_module_background_tasks` to the host's dependencies. Their tables had
  never been in this history (the framework keeps `background_tasks_task_execution`
  in its initial schema, which this host never had), so `c9e3a5f1b7d2` creates it.
  Then, chained linearly: `b5d3f08a6e17`, `e878882924e7`, `bb906e1a1089`,
  `1f5985daa10b` (background_tasks), `f733c7938fd1` (sharing), `a625f0b7c912` and
  `a626b1c8d023` (users).
- **0.0.42**: `b31a70971001` (background_tasks resource columns) and
  `f5b1c3e8a207` (`file_storage_stored_file.size_bytes` to `BIGINT`) follow the
  images head. `f5b1c3e8a207` was ported **without** its upstream
  `("file_storage",)` branch label, because `ca297bbf33bf` already carries it
  here.
- **0.0.43**: `a738c2e4f601` and `e731a1b2c3d4`, after `c4e9b2a7d613`.
  `e731a1b2c3d4` refuses to run while two accounts' emails differ only by letter
  case, and prints them masked (`a***@host`) with the query that lists them.
- **0.0.44**: `e805a1b2c3d4`, `c5d8e2f1a903` and `f6c2d4e8b109`.
- **0.0.45**: the model is `AwareDateTime` (was `TIMESTAMPAware`), which SQLite
  reports as a type change against the reflected `TIMESTAMP`. `0a30d2baa903` is
  shipped and stays as it was.
- **0.0.46**: `e480d7dd348f` (`users_oauth_account` profile columns) follows the
  then head `541bfbe29a28`.
- **Host-only correction** (not an upstream port): `c7a41e9d2b60` follows
  `e480d7dd348f` and retypes `users_access_token.expires_at` on SQLite only
  (a no-op on Postgres), so databases created before and after the 0.0.45 type
  change converge without editing a shipped revision.
- **Not ported**: upstream's `b8d4f2a6c901` (audit_log) and `c9d2e4f6a810`
  (oidc). Neither module is installed here, so their tables do not exist.
