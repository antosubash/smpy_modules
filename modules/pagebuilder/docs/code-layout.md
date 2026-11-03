# Code layout

Pagebuilder follows the repository's [module layout](../../../docs/module-layout.md).

| Area | Responsibilities |
| --- | --- |
| `pagebuilder/core/` | Boot, settings, shared services, permissions, content locale policy and tenancy |
| `pagebuilder/content/` | Pages and workflow in `service/`, snapshots, redirects, board queries, site layout and navigation |
| `pagebuilder/media/` | Media storage, image processing, queries, upload service, usage and Open Graph images |
| `pagebuilder/scheduling/` | Per-tenant scheduled publication loop |
| `pagebuilder/web/` | Endpoints, dependencies, access and CSRF, menu, public cache, language and translated public copy |
| `pagebuilder/ui/` | Components, hooks, utilities, fields, block conversion and translation |
| `tests/` | Matching areas and shared builders/harnesses in `support/`; `pg_support.py` remains at the root |

The root retains `module.py`, `models/`, `contracts/`, real Inertia `pages/`,
`locales/`, `static/` and `py.typed`. The host discovers `puck-blocks.ts` through
its root-level glob; this registry loads contributors' `pagebuilder-blocks.ts`
files. These discovery and resource paths are pinned in `tests/core/test_layout.py`.

The content service facade lives in `content/service/pages.py`; area initializers
contain only docstrings. `content/service/_host.py` still declares each mixin's
requirements. Public consumers continue through `pagebuilder.contracts`.
