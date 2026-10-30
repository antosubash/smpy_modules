# Module layout

How the files of a module in `modules/<name>/` are organised. `images`
(`modules/images`) follows it in full and is the reference; its own map is
[`modules/images/docs/code-layout.md`](../modules/images/docs/code-layout.md).
The other modules predate it and move towards it one step at a time (see
[Moving an existing module](#moving-an-existing-module)).

The aim is that someone new finds a file by asking *which feature is this?*,
then opening that folder. A package root with thirty files answers nothing.

## The module directory

```
modules/<name>/
  <package>/        the Python package, with the frontend inside it (below)
  tests/            pytest suite, mirroring the package (below)
  docs/             the module's own docs; index.md first
  README.md  NOTICE  pyproject.toml  package.json  tsconfig.json
```

Nothing else lives at this level.

## The package root

Only files that something else looks up by name stay at the top of the
package. Moving one breaks a host, a
worker or a sibling module silently, while the module's own tests keep
passing (they import by whatever path the file has). Pin each with a test
that loads it the way its consumer does, like images'
`tests/core/test_task_discovery.py`.

| Path | Who looks it up |
| --- | --- |
| `__init__.py`, `module.py` | Python; the `simple_module` entry point |
| `models/` | `simple_module_db` imports `<package>.models` for migrations |
| `tasks.py`, `task_config.py` | `background_tasks`: Celery autodiscovery and the routes/beat loader |
| `pages/` | the host's page glob; real Inertia pages only (`scripts/check_rules.py`) |
| `locales/` | the framework's i18n registry |
| `index.ts` | `package.json` `exports`; the module's public TS surface |
| `pagebuilder-blocks.ts` | pagebuilder's `puck-blocks.ts` glob (`*/*/pagebuilder-blocks.ts`) |
| `images_extensions.py`, `images-steps.ts` | a plugin's file that another module imports or globs by name |

**Nothing else.** In images that leaves four Python files at the root.
Settings, tenancy, the clock, the menu and helpers all go into a package. So
does what every feature uses, which goes in `core/`: `core/constants.py`,
`core/errors.py` and `core/events.py`, under an `__init__.py` that holds only a
docstring. Keep `core/` short: if only two features use something, it belongs
to one of them.

## Feature packages

Group by *what the code is about*, not by technical layer. Images has
`access/`, `tenancy/`, `billing/`, `storage/`, `serving/`, `jobs/`, `ingest/`,
`imports/`, `pipeline/`, `steps/`, `processing/`, `ai/`, `regroup/` and `map/`.

These technical packages are shared by every module, with the same names:

| Package | Holds |
| --- | --- |
| `models/` | SQLModel tables, one file per table or a small family |
| `schemas/` | request and response shapes |
| `services/` | reads and writes the endpoints share |
| `endpoints/` | routers: `api/` (JSON), console views, public views; request deps, CSRF, the menu |
| `contracts/` | the only thing other modules may import. Anything else can move without notice |
| `settings/` | the DB-backed settings class (`__init__.py`) and what is read at boot (`boot.py`) |
| `tenancy/` | binding the tenant per request, the tenancy mode, the request context |

Rules for a package:

- **The public face may sit in `__init__.py`.** Then `from <pkg> import
  billing; billing.check(...)` reads the same as before the package existed.
  This only works if `__init__.py` stays light, because Python runs it whenever
  any sibling is imported. Heavy code goes in a named module, with an
  `__init__.py` that holds only a docstring (images' `serving/respond.py`).
- **Every module imports on its own.** In a fresh interpreter,
  `python -c "import <pkg>.<mod>"` must succeed for every module, or there is
  an import cycle waiting for a different entry point. Break a cycle with a
  call-time import and a comment saying why.
- **Private helpers live in the package they serve**, named with `_`: for
  example `tenancy/_mode.py`, not `_tenancy_mode.py` at the root.
- **The 300-line cap still applies** (`scripts/check_file_size.py`). Split a
  file by responsibility, inside its package.

## Frontend

The TS/TSX lives inside the package, next to the Python:

| Path | Holds |
| --- | --- |
| `pages/` | Inertia pages only. The page name is derived from the path |
| `components/<feature>/` | components, grouped by the same features as the Python |
| `components/` (root) | only what every feature uses (`ConfirmDialog`, the layout) |
| `hooks/`, `utils/` | hooks and plain TS. `utils/i18n.ts` derives `keys` from `locales/en.json` |
| `page-tests/` | page-level tests, `test-dom.tsx` and shared test support. Not shipped in the wheel |

A component's unit test sits beside it (`Foo.test.tsx`). Test helpers never
sit at the package root: the wheel excludes `page-tests/**`, `**/*.test.*` and
`**/test-dom.tsx`.

## Tests

```
tests/
  conftest.py        fixtures shared by every folder
  pg_support.py      the Postgres opt-in; identical in every module (see below)
  support/           helpers, named for what they set up: access.py, serve.py, …
  fixtures/          files the tests read
  <feature>/         one folder per package: tests/access/, tests/serving/, …
    __init__.py      tests/ is a package, so helpers import as tests.support.x
    test_*.py
  core/              module boot, contracts, settings, task discovery
```

A new test goes in the folder of the feature it exercises.

**Parity exceptions.** `tests/pg_support.py` and the tenancy helpers are
copies kept identical across modules by `scripts/tests/test_helper_parity.py`
(`parity_tenancy.py`, `parity_families.py`). Those checks compare paths and
path depth, so `pg_support.py` stays at the tests root. When a module moves its
tenancy copy into `tenancy/`, update the module's entries in
`parity_tenancy.py` in the same commit.

## Moving an existing module

Do it in small PRs, one module at a time, each containing only moves:

1. **Pin first.** Add the discovery tests for the files in the table above,
   so a wrong move fails.
2. **Move with a script, not by hand.** `git mv`, then rewrite
   `from <pkg> import x` and the `<pkg>.x` dotted strings (`mock.patch`
   targets, `monkeypatch` paths). For a reusable one, see the images scripts in
   `.superpowers/sdd/images-module/restructure/` (git-ignored scratch; copy
   whatever you need from them).
3. **Then the tests**, into `tests/<feature>/` and `tests/support/`.
4. **Check:**
   - the fresh-import check over every module;
   - the module's suite, plus `host/tests` and `scripts/tests` (parity);
   - `make lint`;
   - the e2e specs of the module;
   - if the module has Celery tasks, start a worker and check that it
     registers them.
5. **No logic changes in the same PR**, so the review is just "is every move
   right".

### Where each module stands (2026-10-30)

| Module | Root `.py` files | Flat `tests/test_*.py` | State |
| --- | --- | --- | --- |
| images | 4 | 0 | follows this layout |
| ai | 13 | 14 | not moved yet |
| billing | 28 | 53 | not moved yet |
| news | 27 | 78 | not moved yet |
| pagebuilder | 30 | 99 | not moved yet |
| records | 37 | 181 | not moved yet |

Update this table when a module moves.
