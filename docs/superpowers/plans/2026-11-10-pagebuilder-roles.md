# PageBuilder role rows (#320) — plan

Design: `docs/superpowers/specs/2026-11-10-pagebuilder-roles-design.md`.

All tasks are sequential and small; none is marked hard.

1. **Test first.** `host/tests/test_pagebuilder_roles_migration.py`, real alembic
   on a SQLite file (pattern: `test_news_tenant_migration.py`):
   - upgrade from `4381e1c2ac7e` to heads creates the three roles with their
     fixed ids and descriptions;
   - a `pagebuilder_editor` row inserted before the upgrade keeps its id and
     description, and the other two are still created;
   - downgrade to `4381e1c2ac7e` removes unassigned rows and keeps one assigned
     through `users_user_role`;
   - `alembic check` is clean.
   Done: the tests fail because the revision does not exist.
2. **Migration.** `host/migrations/versions/541bfbe29a28_pagebuilder_seed_roles.py`
   off `4381e1c2ac7e`, values inlined. Done: task 1's tests pass,
   `scripts/check_migration_heads.py` passes.
3. **Docs.** "Roles" section in `modules/pagebuilder/docs/operations.md` (what to
   copy into a consuming host), the Install step pointing at it, and a CHANGELOG
   0.0.15 Fixed entry. Done: `make lint` passes.
