# Records code layout

Records follows the repository's [module layout](../../../docs/module-layout.md).
Find a file by its responsibility:

| Area | Responsibilities |
| --- | --- |
| `core/` | Constants, settings and their validation, boot, service container, domain events, content locales, tenant binding/guard, health and permission registration |
| `web/` | API/view endpoints, request dependencies, CSRF, body limit, document language, menus and media-backend discovery |
| `records/` | Collections, record services, schema-change jobs, deferred jobs, index/query/rebuild, demo seeding, CLI implementation and isolated pattern workers |
| `schema/` | Field definitions, payload model compilation and schema diffs |
| `public_submissions/` | Website submissions, consent, newsletter links, mail templates, delivery claims and retention |
| `ui/` | Components, hooks, utilities and page tests |

`module.py`, `models/`, `contracts/`, `pages/`, `locales/`, `index.ts` and
`pagebuilder-blocks.ts` retain the names their consumers discover. JSON catalogues
remain in `locales/`; Python content-language policy lives in `core/locales.py`.
The documented `python -m sm_records.cli` command still parses and dispatches at
the package root; its helpers live in `records/cli/`.

The root `index.py` preserves the documented index-provider API (`__all__`),
re-exporting the same objects from `records/index/`. Its private query and writer
modules are implementation details. The root `collections.py` and `seed.py` similarly preserve the documented
collection-declaration and in-process seeding APIs. Their implementations
live under `records/`; no private submodule aliases are provided.
The pattern pool lives in `records/_pattern_worker.py`; its children still run
the same embedded standard-library program with `python -I -S -c`, under the
same bounded deadlines. Mail templates remain beside the submission mail code.

Python tests mirror these areas. Shared fixture builders and HTTP/tenant/race
harnesses live in `tests/support/`; `conftest.py` re-exports fixtures, and
parity-managed `pg_support.py` stays at the tests root. Performance tests keep
their explicit opt-in directory. Frontend unit tests stay beside their subject;
page tests and DOM support live in `ui/page-tests/`. Wheels exclude them.

Files close to the line cap split along existing responsibilities: event
payloads, record reads, translation slugs, unique claims, import envelopes,
relation references, reindex markers, sort terms/plans, seed field builders,
type write helpers, locale props, date conversions, media value classification,
editor shortcut handling and reusable page props/state.
