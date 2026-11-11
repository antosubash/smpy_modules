# PageBuilder role rows (#320)

## Goal & scope

`pagebuilder_editor`, `pagebuilder_publisher` and `pagebuilder_approver` are
mapped to permissions in `register_permissions`, but no `users_role` row exists
for them, so the users admin cannot assign them. Make them assignable.

In: a host data migration that creates the three rows, a recipe for consuming
hosts, docs and CHANGELOG. Out: any change to the permission mapping, the users
admin UI, or framework-side seeding of mapped roles (an upstream idea, not
filed here).

## Approach

**A host data migration**, modelled on the `user` role seed `42b922de3574`.

Rejected:
- *Seed on pagebuilder's `on_startup`* (the issue's second option). The users
  module deliberately never re-creates a role at boot: "a role an admin deleted
  must stay deleted". A startup seed would bring a deleted editorial role back
  on every restart. It would also make pagebuilder depend on the users module,
  which it does not today.
- *A pagebuilder helper that host migrations import.* A migration must keep
  meaning what it meant when it was written, so values are inlined (the same
  rule `42b922de3574` follows).

## Design

New revision off the single head `4381e1c2ac7e`:
`host/migrations/versions/<rev>_pagebuilder_seed_roles.py`.

- **upgrade:** for each of the three names, insert `(id, name, description)`
  into `users_role` unless a row with that name already exists.
  - IDs are fixed and inlined: `uuid5(NAMESPACE_URL, "simple_module:role:<name>")`,
    written as literals.
  - Descriptions: "PageBuilder: edit pages", "PageBuilder: edit and publish
    pages", "PageBuilder: edit, publish and approve pages".
- **downgrade:** delete each of the three rows only if no `users_user_role`
  row references it. An assigned role stays.
- **Recipe for consuming hosts:** a "Roles" section in
  `modules/pagebuilder/docs/operations.md`. Migrations belong to the host, so it
  shows the revision to copy (or the equivalent `INSERT`). The section notes
  that without the rows the roles cannot be assigned, and per-user grants are
  the only option.
- **CHANGELOG:** a 0.0.15 "Fixed" entry, with an upgrade note pointing at the
  recipe.

## Decisions made

- **Seed on every upgrade, not only on a fresh install.** This differs from
  the `user` seed, which skips installs that already have users. No release has
  ever created these rows, so a missing one cannot mean an admin removed it. An
  admin who deletes one afterwards is never overridden, because the migration
  runs once.
- **Insert by name, skip if present.** A host that seeded the rows itself, as
  BioGarden does, keeps its own rows and IDs.
- **Deterministic IDs.** The same three IDs on every host, which makes support
  and bundle comparisons easier. Nothing relies on them.

## Testing

`host/tests/test_pagebuilder_roles_migration.py` runs real alembic against a
SQLite file, like `test_news_tenant_migration.py`. It covers:
- upgrade from `4381e1c2ac7e` creates all three rows;
- an existing `pagebuilder_editor` row is kept unchanged;
- downgrade removes unassigned rows and keeps an assigned one;
- `alembic check` stays clean.

The Postgres `alembic check` runs in CI. No browser QA: there is no UI change
beyond the role now appearing in the users admin's list.

## Risks

- The role-list cache in the users admin (`users.core.roles_cache`, 300 s TTL)
  is per process. After `make migrate` on a running app, the new roles appear
  within five minutes or on restart. That is acceptable for a migration.
