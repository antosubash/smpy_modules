# Host translation overrides

The framework ships the `@simple-module-py/ui` chrome strings (sidebar,
topbar, command palette, error pages) inside `simple_module_hosting`
(`ui_locales/`). Since 0.0.38 that catalogue includes German (upstream #492),
as do the framework modules' own screens. It no longer reads a
`packages/ui/locales/` directory, which this repo used to vendor.

Until 0.0.38 this host translated the whole `ui` namespace itself. Now
`de.json` keeps only the labels the host words differently from the
framework's German (shorter relative times, "Inhalte", "Suche",
"Adminbereich", the demo banners), through the framework's override
mechanism: `host/locales/overrides/<lang>.json`, keyed by full dotted path,
applied after every catalogue. An override can only replace a key some
catalogue already defines, so a typo is skipped and logged rather than
inventing copy.

The empty `host/locales/en.json` and `de.json` exist only because the
framework registers a `host` namespace whenever `host/locales/` exists, and
logs a missing-file warning per locale without them. The host has no strings
of its own.

When the framework pin moves, `host/tests/test_ui_locales.py` fails if the
German console would miss a `ui` key, if an override names a key the
framework dropped, or if an override has become identical to the framework's
own German (delete it then).
