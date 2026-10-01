# `@simple-module-py/ui` strings

`en.json` and `es.json` are copied verbatim from the framework repository at
**v0.0.35** (`packages/ui/locales/` in `antosubash/simple_module_python`).

The admin chrome from `@simple-module-py/ui` (sidebar, topbar, command palette,
error pages) renders its labels through `t(keys.ui.…)`. The framework's server
loads that `ui` namespace from `<project root>/packages/ui/locales/`
(`simple_module_hosting.i18n_manifest.build_i18n_registry`), a path that exists
in the framework's own repository but ships in neither the npm package (its
`files` are `src` and `README.md`) nor any wheel. Without this directory every
one of those labels renders as its raw key — `ui.sidebar.open` instead of
"Open sidebar".

When the host's framework pin moves, copy the two files from the new tag.
`host/tests/test_ui_locales.py` fails if the installed `ui` package uses a key
this catalog does not have.
