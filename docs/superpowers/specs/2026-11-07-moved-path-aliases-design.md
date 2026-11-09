# Compatibility aliases for the 0.0.14 module-layout moves (#319)

## Goal and scope

v0.0.14 moved ai, billing, news, pagebuilder and records into the module layout
(`docs/module-layout.md`) with no aliases, so every downstream import of an old path
broke on upgrade (BioGarden: about 40 TS and 20 Python imports). 0.0.15 restores every
old path as a deprecated alias, and the aliases are removed in **0.0.17**: two releases of
warnings, like the framework's 0.0.44 → 0.0.46.

In scope, for all five modules:

- every Python module and package that moved or was deleted between `v0.0.13` and
  `v0.0.14` (318 files), importable again under its old dotted name, with a
  `DeprecationWarning` that names the new path;
- every moved TypeScript/TSX/CSS file (about 470), importable again under its old
  `@simple-module-py/<mod>/…` path;
- the silent trap: `from pagebuilder import locales` (and the same in news and records)
  returns the real `core.locales` module again, instead of an empty namespace package;
- `CHANGELOG.md` (new, repo root) with a 0.0.14 entry (moved paths, `@puckeditor/core ^0.24`)
  and a 0.0.15 entry (aliases, their removal release).

Out of scope: tests, e2e specs and docs that moved (nobody imports them); images (it was
already in the layout before 0.0.14); static type-checking of old paths downstream (the
runtime import works; a type checker may still flag it, which is the warning we want).

## Approach

**Python: one import hook per package, driven by a generated table.** Each package gets
`core/moved_paths.py` (the hook, about 60 lines) and `core/moved_paths.json` (old → new,
generated from the git rename list, plus `remove_in`). The package `__init__.py` calls
`install()`, which puts a `MetaPathFinder` at the front of `sys.meta_path` that answers only
for names in its table. Its loader imports the new module, calls the framework's
`deprecated_module(old, remove_in="0.0.17", use=new)` (in `simple_module_core` since 0.0.38,
the lowest floor here, so no floor changes) and returns the same module object. The old
and new names are therefore one object, and class identity and module state are shared.

- An aliased package also maps its prefix: `pagebuilder.service.X` → `pagebuilder.content.service.X`,
  so no old submodule is ever loaded a second time under its old name.
- A file that was split or deleted (`sm_ai/metering.py`, `sm_records/index/query.py`, and
  `pagebuilder/utils/api.ts`, whose `listMedia`/`uploadMedia` went to `ui/utils/mediaApi`)
  maps to a list of modules. The hook builds a module that re-exports the names the old file
  exported at v0.0.13. Names that exist nowhere any more are listed in the CHANGELOG as
  removed. They are not invented.
- The finder never shadows a path that is a real module today; the generator refuses one.

Rejected: a shim `.py` file per old path, the framework's style. That would put 318 files
back into the package roots the layout just emptied, and removing them takes 318 deletions
instead of five. A `package.json` `exports` map for TypeScript was also rejected. The host
resolves `@simple-module-py/<mod>` to the installed package directory, and an `exports`
pattern target gets no extension probing in Vite or tsc, so extensionless imports would
still fail.

**TypeScript: generated re-export stubs at the old paths.** Each stub is
`export * from '<relative new path>';`, plus `export { default } from '…';` when the target
has a default export, under a `/** @deprecated moved to … — removed in 0.0.17 */` header.
The three CSS files get an `@import`. Nothing under `pages/` moved, so no stub can register a page.

**One script owns all of it.** `scripts/moved_paths.py`:

- `--generate` runs once, from the rename list of `git diff -M v0.0.13 v0.0.14`, and writes
  the JSON tables and the TS stubs;
- `--check` runs in `make lint` and CI. It checks that the stubs and tables agree, that
  every target exists, and that a stub has `export { default }` exactly when its target has
  one. It also checks that no non-stub source in the repo imports an old path: an internal
  relative import into a stub dir would now resolve silently, and that must stay an error.

## Decisions made

- The hook is duplicated in the five packages, since modules share no code except through
  the framework (the same as the `core/tenancy` copies). A parity test keeps the five copies
  byte-identical.
- The removal release is enforced. A host test fails once the lockstep version reaches
  `remove_in`, so 0.0.17 cannot ship with the aliases still present. Removal then means
  deleting the stubs, the two `core/moved_paths.*` files and the `install()` lines.
- The warning category is `DeprecationWarning`, raised through the framework helper, so the
  message names the importer's file and line.
- `CHANGELOG.md` lists the moves per module by old and new directory (for example
  `components/` → `ui/components/`) plus the individual exceptions, not all 789 rows. The
  JSON tables are the complete list, and the changelog links to them.
- `CLAUDE.md` and `docs/module-layout.md` get a short note: old paths stay aliased until
  0.0.17, new code must not use them, and `--check` enforces that.

## Testing

- Python (host test, parametrized over every module's table): importing each old name warns,
  and `sys.modules[old] is importlib.import_module(new)`. A split module exposes every name
  the old file exported at v0.0.13, and a test reads that list from the table. Further tests
  cover `from pagebuilder import locales; locales.is_default` (and news, records), the
  prefix mapping for a submodule that the table does not list, and the hook's parity across
  the five packages.
- TypeScript: `make typecheck` compiles every stub, so a stub with a missing target fails
  tsc. `moved_paths.py --check` has its own tests in `scripts/tests/`, run on a small fake
  tree.
- The existing full suites, plus one wheel build of pagebuilder to confirm that the JSON and
  the stubs ship and that no test file enters the wheel.
- The change has no UI, so `/ship` runs with `--skip-browser`. The e2e suite still runs in CI.

## Risks

- A v0.0.13 file whose names were renamed (not only moved) has no target for those names.
  The generator lists them and the CHANGELOG records them as removed.
- Vitest coverage or Biome may object to about 470 code-free files; if so, they are excluded
  by path glob, not by loosening a rule.
- A wheel consumer that imports a stub gets the deprecation only as a JSDoc tag in the
  editor, never at runtime. This is accepted: there is no runtime warning channel for ESM
  imports.
