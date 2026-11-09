# Moved-path aliases (#319): implementation plan

Design: `docs/superpowers/specs/2026-11-07-moved-path-aliases-design.md` (approved 2026-11-07).
Modules: ai (`sm_ai`), billing (`sm_billing`), news (`news`), pagebuilder (`pagebuilder`),
records (`sm_records`). Removal release: `0.0.17`. Source of moves: `git diff -M v0.0.13 v0.0.14`.

Tasks run in order. Each one starts with a failing test, then the code, then the targeted
tests, then a commit `feat(moved-paths): <task>`.

## Task 1: the import hook (hard)

- Files: `modules/pagebuilder/pagebuilder/core/moved_paths.py`, then a byte-identical copy in
  the other four packages' `core/`.
- Behaviour: `install(package: str)` reads `core/moved_paths.json` beside it, holding
  `{"remove_in": "...", "modules": {old: new | [new, ...]}, "packages": [old, ...]}`, and
  inserts one `MetaPathFinder` at the front of `sys.meta_path`. Installing twice must not add
  a second finder.
  - For a name in `modules`, or one under an old package prefix, the finder returns a spec
    whose loader imports the target and calls
    `deprecated_module(old, remove_in=..., use=new)`.
    - With one target, the loader returns the target module object itself.
    - With a list (a split or deleted file), it returns a fresh module carrying the public
      names each target exports. An optional `"names": {old: [...]}` restricts the module to
      exactly those names.
  - Any other name gets `None`, so normal import resolution carries on.
- The package `__init__.py` gets `from .core.moved_paths import install` and
  `install(__name__)`. Records' docstring stays.
- Test first, in `host/tests/test_moved_paths.py`, using a temporary fake package:
  - the alias is identical to the new module and the import warns;
  - the prefix mapping works for an unlisted submodule;
  - a split module gets its names;
  - an unknown name is not intercepted;
  - `install` is idempotent.
- Done when those tests pass.

## Task 2: the generator and checker (hard)

- File: `scripts/moved_paths.py`. Tests: `scripts/tests/test_moved_paths_script.py`, on a tiny
  fake repo built in `tmp_path`, with a fake rename list passed in. The tests must not depend
  on git tags.
- `--generate`:
  - Reads `git diff --name-status -M50 v0.0.13 v0.0.14 -- modules`. It skips tests (`/tests/`,
    `*.test.*`, `__tests__`, `test-dom.tsx`, `*-test-support.ts`), e2e and docs.
  - Python renames go into each package's `core/moved_paths.json`: `__init__.py` gives a
    package entry, any other file a module entry.
  - For every old module, it parses the v0.0.13 source (`git show v0.0.13:<path>`) for
    top-level public names. A name the target lacks is looked up across the package's
    current modules; if found, the entry becomes a list with a `names` entry.
  - Deleted files are handled the same way.
  - Names found nowhere are printed and written under `"removed"` in the JSON.
  - It refuses an old name that is a real module today, except a namespace dir with no
    `.py` files, such as `locales/`.
  - TS/TSX/CSS renames become stubs at the old path (see the design). A split TS file
    (`pagebuilder/utils/api.ts`) re-exports the moved names from their new file.
    v0.0.13 exports are found by regex over `export (const|function|class|type|interface|enum|default|{…})`.
- `--check`, run by `make lint` and CI next to `check_rules.py`:
  - every JSON target imports to a real file;
  - every stub is exactly what `--generate` would write;
  - a stub re-exports `default` exactly when its target has a default export;
  - no non-stub `.py`, `.ts` or `.tsx` under `modules/`, `host/` or `scripts/` imports an old
    path: Python absolute imports, TS relative imports that resolve into a stub, and
    `@/…` / `@simple-module-py/<mod>/…` specifiers that land on a stub.
- Done when the script tests pass, `--generate` has been run and its output committed (a
  separate commit `feat(moved-paths): generated aliases`), and `--check` passes.

## Task 3: real-table tests and the removal guard

- `host/tests/test_moved_paths.py` additions:
  - parametrized over every entry of all five JSON tables: importing the old name inside
    `pytest.warns(DeprecationWarning)` succeeds, and it is the target (single), or has every
    listed name (split);
  - `from <pkg> import locales` plus `locales.is_default` for pagebuilder, news and records;
  - the five `core/moved_paths.py` copies are byte-identical (or register them in
    `scripts/tests/parity_families.py` if that fits better);
  - the removal guard: once the version in the root `pyproject.toml` reaches `remove_in`,
    the test fails with "delete the 0.0.14 moved-path aliases".
- Done when the targeted tests pass and the existing host deprecated-path guard still passes.

## Task 4: lint and CI wiring, tooling fallout

- `Makefile` `lint` and `.github/workflows/ci.yml` (next to `check_rules.py`) run
  `uv run python scripts/moved_paths.py --check`.
- Run `make typecheck` and `npx biome check host modules scripts tests`, plus `ruff`,
  `check_file_size.py`, `check_rules.py` and the vitest coverage config. Fix any fallout
  from the stubs by path-scoped excludes only.
- Done when all of those pass.

## Task 5: docs (routine)

- `CHANGELOG.md` (new) gets a 0.0.15 (unreleased) entry for the aliases and their removal in
  0.0.17, and a 0.0.14 entry for the module-layout moves.
  - The 0.0.14 entry lists the moves per module by directory (`components/` →
    `ui/components/`, …) plus the exceptions from the JSON (`pagebuilder.service`,
    `listMedia`/`uploadMedia`, the `removed` names), and the `@puckeditor/core ^0.24` bump.
  - It links the JSON tables as the full list.
- `CLAUDE.md` (module-layout paragraph) and `docs/module-layout.md` get a short note: the old
  paths are aliased until 0.0.17, new code must use the new path, `moved_paths.py --check`
  enforces it, and the removal guard says when to delete the aliases.
- Done when the docs agree with the code.

## Task 6: full verification

- Run the full Python suites, Postgres included (`PYTEST_WORKERS=8`, one suite at a time),
  vitest, a `uv build` of pagebuilder checked with `scripts/tests/test_wheel_contents.py`,
  and `make lint`, with Biome scoped as above. Then run `/ship --skip-browser`.

Independent: none. Tasks 2 and 3 depend on task 1, and task 5 depends on the generated
output from task 2. Hard: tasks 1 and 2.
