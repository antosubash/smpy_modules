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
package. Moving one breaks a host, a worker or a sibling module silently,
while the module's own tests keep passing (they import by whatever path the
file has).

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
| `contracts/` | other modules: the only import path they may use |

**Nothing else.** In images that leaves four Python files, two TS files and
four folders (`models/`, `pages/`, `locales/`, `contracts/`) beside the seven
areas below. Pin each looked-up file with a test that loads it the way its
consumer does.

## Areas

Everything else sits in one of a few **areas**, so the root lists about a
dozen folders however big the module grows. Inside an area, one folder per
feature.

| Area | Holds |
| --- | --- |
| `core/` | What every feature builds on: `constants.py`, `errors.py`, `events.py`, and the cross-cutting packages `settings/`, `tenancy/`, `clock/`, `access/`, `storage/`, `billing/` (whichever the module has) |
| `web/` | The HTTP side: `endpoints/` (routers, request deps, CSRF, the menu), `schemas/` (request and response shapes), `services/` (reads and writes the endpoints share), `serving/` if the module serves files |
| one per domain | The module's own subject. Images has `ingest/` (uploads, `imports/`), `pipeline/` (the engine, `steps/`, `processing/`, `ai/`), `jobs/` (beats, `regroup/`) and `map/`. A news module would have `content/`, `scheduling/`, … |
| `ui/` | The frontend that is not a page (below) |

Choosing where a package goes:

- **Used by most features** → `core/`. If only two features use it, it
  belongs to one of them.
- **Part of answering a request** (routers, shapes, the reads and writes
  they share) → `web/`.
- **Otherwise** → the domain area it is about. Make a new area only for a
  subject with several features of its own; a single feature goes inside the
  area closest to it.

Rules for a package:

- **The public face may sit in `__init__.py`.** Then `from <pkg>.core import
  billing; billing.check(...)` reads the same as before the package moved.
  This only works if `__init__.py` stays light, because Python runs it whenever
  any sibling is imported. Heavy code goes in a named module, with an
  `__init__.py` that holds only a docstring (images' `web/serving/respond.py`).
  An area's own `__init__.py` holds only a docstring.
- **Every module imports on its own.** In a fresh interpreter,
  `python -c "import <pkg>.<mod>"` must succeed for every module, or there is
  an import cycle waiting for a different entry point. Break a cycle with a
  call-time import and a comment saying why.
- **Private helpers live in the package they serve**, named with `_`: for
  example `core/tenancy/_mode.py`, not `_tenancy_mode.py` at the root.
- **The 300-line cap still applies** (`scripts/check_file_size.py`). Split a
  file by responsibility, inside its package.

## Frontend

The TS/TSX lives inside the package, next to the Python:

| Path | Holds |
| --- | --- |
| `pages/` | Inertia pages only, at the root because the page name is derived from the path |
| `ui/components/<feature>/` | components, grouped by the same features as the Python |
| `ui/components/` (top) | only what every feature uses (`ConfirmDialog`, the layout) |
| `ui/hooks/`, `ui/utils/` | hooks and plain TS. `ui/utils/i18n.ts` derives `keys` from `locales/en.json` |
| `ui/page-tests/` | page-level tests, `test-dom.tsx` and shared test support. Not shipped in the wheel |

A component's unit test sits beside it (`Foo.test.tsx`). Test helpers never
sit at the package root: the wheel excludes `page-tests/**`, `**/*.test.*` and
`**/test-dom.tsx`. Biome lints `modules/*/*/ui/**` as well as the older
`components/`, `hooks/` and `utils/` folders.

## Tests

```
tests/
  conftest.py        fixtures shared by every folder
  pg_support.py      the Postgres opt-in; identical in every module (see below)
  support/           helpers, named for what they set up: access.py, serve.py, …
  fixtures/          files the tests read
  <area>/<feature>/  mirrors the package: tests/core/access/, tests/web/serving/, …
    __init__.py      tests/ is a package, so helpers import as tests.support.x
    test_*.py
  core/              module boot, contracts, settings, task discovery
```

A new test goes in the folder of the feature it exercises; a test of an
area's top-level code sits at the top of that area's folder.

**Parity exceptions.** `tests/pg_support.py` and the tenancy helpers are
copies kept identical across modules by `scripts/tests/test_helper_parity.py`
(`parity_tenancy.py`, `parity_families.py`). Those checks compare paths and
path depth, so `pg_support.py` stays at the tests root. When a module moves its
tenancy copy into `core/tenancy/`, update the module's entries in
`parity_tenancy.py` in the same commit.

## Moving an existing module

Do it in small PRs, one module at a time, each containing only moves:

1. **Pin first.** Add the discovery tests for the files in the table above,
   so a wrong move fails.
2. **Move with a script, not by hand.** `git mv`, then rewrite
   `from <pkg> import x` and the `<pkg>.x` dotted strings (`mock.patch`
   targets, `monkeypatch` paths), but not where the package name is an
   attribute (`app.state.<pkg>.settings` is not the `settings` package),
   and rewrite each relative TS import from where its file used to be.
   For a reusable one, see the images scripts in
   `.superpowers/sdd/images-module/restructure/` (git-ignored scratch; copy
   whatever you need from them).
3. **Then the tests**, into `tests/<area>/<feature>/` and `tests/support/`.
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

| Module | Root `.py` files | Root folders | Flat `tests/test_*.py` | State |
| --- | --- | --- | --- | --- |
| images | 4 | 11 | 0 | follows this layout |
| ai | 13 | 6 | 14 | not moved yet |
| billing | 28 | 9 | 53 | not moved yet |
| news | 27 | 10 | 78 | not moved yet |
| pagebuilder | 30 | 14 | 99 | not moved yet |
| records | 37 | 14 | 181 | not moved yet |

Update this table when a module moves.
