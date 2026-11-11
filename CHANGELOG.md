# Changelog

One version covers every package in this repo (releases are lockstep). Entries
name the module they affect.

## 0.0.16 (unreleased)

### Fixed

- **newsletter requires records, news and pagebuilder 0.0.16** (#333). Its
  floors said 0.0.13, but the `contracts` modules it imports
  (`sm_records.contracts.newsletter`, `.newsletter_admin`, `.newsletter_import`,
  `news.contracts.articles`, `pagebuilder.contracts.cards`) are in no release
  before this one, so a host with an older sibling installed kept it and
  newsletter failed at boot with `ImportError`. `scripts/check_sibling_contracts.py`
  (in `make lint` and CI) now fails when a sibling floor's release tag lacks a
  contract module or name its dependant imports.
- pagebuilder and news no longer send `public_csp` on a `304 Not Modified`
  (#322). The browser merges a 304's headers into the cached page, so the
  module's strict policy replaced the page's nonce-based one, and after
  revalidation every script was blocked: a blank page in development, and in
  production the nonce'd scripts and any `register_csp_sources` allowance. A
  browser that already merged the old header keeps it until it next fetches
  the page in full.
- pagebuilder's roles `pagebuilder_editor`, `pagebuilder_publisher` and
  `pagebuilder_approver` can be assigned in the users admin (#320). They were
  mapped to permissions in code, but no `users_role` row existed for them, so
  they never appeared in the role list. The demo host's revision `541bfbe29a28`
  creates the missing rows. **Upgrading:** migrations belong to the host, so a
  consuming host copies that revision into its own history; see "Roles" in
  `modules/pagebuilder/docs/operations.md`.
- pagebuilder and news emit valid JSON-LD for a document containing `<!--`
  (#353). The escape was `<\!--`, and `\!` is not a JSON escape, so a strict
  parser rejected the whole block. Every `<` is now written as `\u003c`.
- The demo host's editor finds wheel-installed modules' blocks on any Python 3
  version (#341). `host/client_app/blocks.ts` globbed `python3.12` only, and a
  glob that matches nothing is silent. A host copied from this one should make
  the same change.
- `.env.example` ships no secret values (#352). It held placeholders whose
  wording neither framework check refuses, so a hand-copied file would have run
  production with a session key and token-signing keys published here. Now
  there is nothing to keep by mistake: production refuses to boot without the
  two users token secrets, and the host generates `SM_SECRET_KEY` itself.
  `make env` appends a generated value for all three.

## 0.0.15

### Deprecated

- **The paths that 0.0.14 moved work again, as deprecated aliases, until 0.0.17
  (#319).** This covers ai, billing, news, pagebuilder and records.
  - Python: importing an old dotted path, such as `from pagebuilder.service import
    PagesService`, returns the module at its new path. It is the same object, so
    classes, tables and state are shared. The import raises a `DeprecationWarning`
    that names the new path and points at the importing line.
  - TypeScript and CSS: every old file under `components/`, `hooks/` and `utils/`
    (and pagebuilder's `conversion/`, `fields/`, `translation/`) is back as a
    re-export stub, marked `@deprecated`.
  - The full old-to-new list is each package's `core/moved_paths.json`.
  - Change your imports to the new paths before 0.0.17, which deletes the aliases.

### Fixed

- `from pagebuilder import locales` (and the same in news and records) returns
  the real `core.locales` module again. In 0.0.14 it imported the data-only
  `locales/` directory as an empty namespace package, and the failure only showed
  later, as an `AttributeError` on `locales.is_default`.

## 0.0.14

### Changed (breaking)

- **ai, billing, news, pagebuilder and records follow the module layout**
  (`docs/module-layout.md`). Their sources moved with no aliases. 0.0.15 restores
  the old paths for two releases (see above).
  - Python: root modules moved into `core/`, `web/` (endpoints, services, deps,
    access) and one folder per domain. Old `endpoints/` became `web/endpoints/`.
  - TypeScript: `components/`, `hooks/` and `utils/` moved to `ui/components/`,
    `ui/hooks/` and `ui/utils/`. Pagebuilder's `conversion/`, `fields/` and
    `translation/` moved under `ui/` as well.
- Moves that are not a straight directory move:

  | Module | Old | New |
  | --- | --- | --- |
  | pagebuilder | `pagebuilder.service` (`PagesService`) | `pagebuilder.content.service.pages` |
  | pagebuilder | `pagebuilder.service.*`, `pagebuilder.snapshots.*` | `pagebuilder.content.service.*`, `pagebuilder.content.snapshots.*` |
  | pagebuilder | `pagebuilder.locales`, `.settings`, `.permissions`, `.tenancy` | `pagebuilder.core.*` |
  | pagebuilder | `pagebuilder.media_service`, `pagebuilder.og_image` | `pagebuilder.media.*` |
  | pagebuilder | `listMedia`, `uploadMedia` in `utils/api` | `ui/utils/mediaApi` |
  | records | `sm_records.services.*`, `sm_records.index.*`, `sm_records.seed.*` | `sm_records.records.services.*`, `.records.index.*`, `.records.seed.*` |
  | records | `sm_records.services` (package exports) | `sm_records.core.services` |
  | news | `news.endpoints.api.articles` | `news.web.endpoints.api.articles` and `._article_listing` |
  | billing | `sm_billing.plans` (`PlanService`, `PlanError`, `seed_default_plan`) | `sm_billing.plans.service` |
  | billing | `sm_billing.admin` | `sm_billing.web.services.admin` and `.subscription_list` |
  | billing | `sm_billing.teardown` | `sm_billing.subscriptions.deletion.teardown` and `.tenant_deleted` |
  | ai | `sm_ai.metering` (`RequiresAiRequest`, `register_meter`, `billing_metering_installed`) | `sm_ai.metering.requests` |

- pagebuilder and news need `@puckeditor/core ^0.24` (was `^0.23`).
