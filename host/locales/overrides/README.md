# Host translation overrides

Framework 0.0.36 ships the `@simple-module-py/ui` chrome strings (sidebar,
topbar, command palette, error pages) inside `simple_module_hosting`
(`ui_locales/`), in English and Spanish only. It no longer reads a
`packages/ui/locales/` directory, which this repo used to vendor.

The demo host speaks German, so `de.json` translates that `ui` namespace
through the framework's override mechanism: `host/locales/overrides/<lang>.json`,
keyed by full dotted path, applied after every catalogue. An override can only
replace a key some catalogue already defines (the English one counts), so a
typo is skipped and logged rather than inventing copy.

The empty `host/locales/en.json` and `de.json` exist only because the
framework registers a `host` namespace whenever `host/locales/` exists, and
logs a missing-file warning per locale without them. The host has no strings
of its own.

When the framework pin moves, `host/tests/test_ui_locales.py` fails if the new
`ui` catalogue gained or dropped a key that `de.json` does not match — add the
German for it here.
