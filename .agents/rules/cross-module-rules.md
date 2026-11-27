---
trigger: model_decision
description: Cross-module dependencies, tenancy, storage, auth, transactions, layout, and Playwright E2E rules for smpy_modules.
---

## Cross-module rules

### Dependencies

- **Modules take framework *ranges*** (`simple_module_core>=0.0.36,<0.1`); the
  host pins *exactly* (`simple_module_hosting==0.0.47`). An `==` in a module makes
  it uninstallable on a newer framework.
- **A requirement on another module here** (news' `pagebuilder` extra) has a `>=`
  floor and a `# floor: <reason>` comment naming what that release first shipped.
  Nothing compares it with the lockstep version: raise floor and comment together
  when a module starts using something newer.
- **The floor must ship what you import**: every `<sibling>.contracts` module and
  name (`import_module("…contracts…")` strings included) at tag `v<floor>`, or in
  the working tree when the floor is the next patch, minor or major after the
  newest tag; any other untagged floor is an error.

### Module boundaries

- **Python: contracts only.** A sibling is imported only through
  `<package>.contracts`; any other non-test import (plain, from, `import_module`/
  `find_spec` strings) fails `check_sibling_contracts.py` (`BOUNDARY_ALLOWLIST`
  empty, #336). Pagebuilder's contracts pin `tenant_id` themselves and the caller
  names the tenant (news' search: `search_pages`/`search_media`, #130). A bundle
  section (`pagebuilder.contracts.bundle`, #80) applies through the restore's
  session and bound tenant, and never commits or resolves a tenant.
- **TypeScript: package root only.** `@simple-module-py/<module>` (its `index.ts`
  via `package.json` `exports`, or `main` for pagebuilder until 0.0.17), never a
  file path or a relative path into `modules/<other>/`.

### Layout and size

- **`docs/module-layout.md`, images is the reference.** A package root keeps only
  what is looked up by name (`module.py`, `models/`, `tasks.py`, `task_config.py`,
  `pages/`, `locales/`, `index.ts`, `pagebuilder-blocks.ts`, `contracts/`); the
  rest goes in `core/`, `web/`, one folder per domain, or `ui/`. Tests mirror the
  areas. Structural changes keep a moves-only review boundary.
- **Only real Inertia pages under `modules/*/*/pages/`.** `import.meta.glob`
  derives page names from the path, so a stray `.tsx` registers a page.
  Extractions go to `components/`, `hooks/`, `utils/`; exceptions in
  `check_rules.py`'s `PAGES_ALLOWLIST`.
- **300 lines per `.py`/`.ts`/`.tsx`**, nothing under `modules/` exempt (only
  `host/migrations/versions/**` is). At 280+, split by
  responsibility when you touch the file; don't trim comments (#133). A mixin
  split from a service declares what it needs as a `Protocol`
  (`pagebuilder/content/service/_host.py`, `news/content/_host.py`); add the
  member there first (`test_*_host.py` enforces it).

### Paths moved in 0.0.14 stay importable until 0.0.17 (#319)

Each moved package's `core/moved_paths.py`, driven by `core/moved_paths.json`,
aliases the old Python paths with a `DeprecationWarning`; generated stubs sit at
the old TS paths (`components/`, `hooks/`, `utils/` folders holding only stubs).
Never edit or import them. `host/tests/test_moved_paths_tables.py` fails once the
version reaches `remove_in`; then, in one change:

- delete the stubs, both `core/moved_paths.*` files, the `install(__name__)`
  lines, the `__getattr__`/`__all__` lines (ai's `metering`, billing's `plans`)
  and the `__path__` lines (records' `index` and `seed`);
- delete `scripts/moved_paths*` with its test, the `--check` lines in the
  Makefile and `ci.yml`, `host/tests/test_moved_paths*.py` and
  `moved_paths_probe.py`, and the stub filter in ai's, billing's and news'
  `test_layout.py`;
- replace pagebuilder's `package.json` `main`/`types` with `"exports": {".":
  "./pagebuilder/index.ts", "./widgets-base.css":
  "./pagebuilder/static/widgets-base.css"}` (until then every deep path must
  resolve), point `host/client_app/styles.css` at
  `@simple-module-py/pagebuilder/widgets-base.css`, and drop that `ALLOWLIST`
  entry in `scripts/check_ts_imports.py`.

A later move needs aliases the same way.

### Migrations

- **Revisions live in `host/migrations/versions/`, never in a module**; each host
  autogenerates its own against the modules' SQLModel tables.
- **`branch_labels = ("<module>",)`** on a module's first revision names it but
  does **not** roll back only that module: `<module>@base` walks the shared
  history beneath it (`downgrade records@base` emptied the database).
- **Exactly one head.** Two PRs off one parent need an empty `alembic merge heads`
  revision. `make migrate` (`upgrade heads`) hides a split; name the parent when
  downgrading through a merge point.
- **Framework tables are ours to migrate.** A framework bump ports each new
  upstream revision unchanged (same id, chained linearly, a duplicate
  `branch_labels` dropped), then `alembic check` on SQLite *and* Postgres.

`host/migrations/README.md` has the detail, the SQLite index check and the port
log (0.0.37–0.0.46, incl. 0.0.40 invalidating every token and `0a30d2baa903`
staying as shipped).

### Framework behaviour to code against

- **Since 0.0.44 most framework modules follow the module layout**; the old flat
  paths (`tenants.resolver`, `settings.service`, …) are gone since 0.0.46
  (`ModuleNotFoundError`; a few remain until 0.1.0). Import the new path, raise the
  floor to the release that shipped it; `host/tests/test_host_boots.py` fails on a
  `deprecated_module` import.
- **Since 0.0.45 a response's own `Content-Security-Policy` is kept beside the app
  policy** (the browser enforces both; framework #870): a module's policy can only
  restrict further, and being static it cannot carry the per-request nonce, so a
  script its `script-src` does not allow is blocked whatever the app allows. news'
  `public_csp` defaults to empty (no second header) and pagebuilder's to
  `frame-ancestors 'none'` alone (no `script-src`; the app's own is `'self'`, so
  public pages are not framed even by the same origin). Set one only to restrict
  something the app policy allows.
- **Production CSP is nonce-based** (0.0.43, no `unsafe-inline`/`unsafe-eval`): a
  template `<script>` needs `nonce="{{ request.state.csp_nonce }}"`, and
  `eval`/`new Function` do not run. An Inertia GET without `X-Inertia-Version`
  gets a 409 (test clients send it); Inertia payloads lose `ETag` and are
  `private, no-store`; page JSON lives only in `<script data-page="app">`.
- **A bare `datetime` field is `timestamptz`** (SQLModel unpinned since 0.0.38).
- **Soft-delete and tenant criteria reach Core statements** on `Model.__table__`
  (subqueries, `INSERT … SELECT`, DML): one that must see the trash needs
  `include_deleted=True` like an ORM query.

### Tenancy (#38, #112)

Tables carry `MultiTenantMixin`, filtered only while a tenant is bound; with
`multi_tenant` off nothing is bound and a read is *unfiltered*.

- **Every pagebuilder, news, records, images, newsletter, events and analytics entry
  point binds a tenant** (`tenancy.bind_admin`/`bind_public`), per request:
  single-tenant → `"default"`; multi → the tenant the framework resolved
  (`request.state.tenant_id`, the active membership; never `user.tenant_id` or a
  header the module reads); none → 403 `tenant_required` (admin), 404 (public). A
  tenant resolved upstream always wins, so a mis-detected child app fails closed,
  and a public answer for another tenant is never shareable-cached (records #196;
  pagebuilder and news #192).
- **Fail-closed guard** in pagebuilder, news, records, images, newsletter and events
  (`core/tenancy/_guard.py`, records' `_tenant_guard.py`, parity-checked by
  `scripts/tests/parity_tenancy.py`, #335): an unbound statement raises
  `TenantUnbound`; a deliberate cross-tenant read is `tenancy.all_tenants(stmt)`;
  Core and `text()` need their own `tenant_id` predicate. **Analytics binds but
  has no guard**: each of its queries carries a `tenant_id` predicate; keep it so.
- **Copies, not imports**: `news.core.tenancy`, `sm_records.core.tenancy` (403 as
  the `{"detail","code"}` envelope), images' copy of records', newsletter's of
  images', events' (`sm_events.core.tenancy`) of newsletter's. Billing reads `request.state.tenant_id` via `context.billing_context`.
- **Background work runs per tenant** under `tenant_context`: schedulers open one
  session per tenant (events' beat: `all_tenants()`, then one session and
  `tenant_scope` per tenant); `images.reconcile`, `images.janitor` and newsletter's hourly
  reconcile enumerate tenants in one narrow `all_tenants()` read (newsletter via
  records' worker-only `subscription_list_tenants`). Tasks never run unscoped.
- **Exceptions** bind the tenant from a verified token: records' signed form
  token (a registration token included), newsletter's `/newsletter/u/`, `/o/`,
  `/c/` and, third, events' `/events/feed/{token}.ics` ([per-module invariants](per-module-invariants.md)).

### Settings and the environment

- **No module reads environment variables for its settings.** They are DB-backed
  (`register_module_settings`; `DbBackedSettings` drops env, `.env` and secrets
  sources): a field goes on the class, not `.env.example`; `SM_PAGEBUILDER_*`
  lines are dead. Set them on the Settings screen or with `scripts/set_setting.py`.
  The only env reads are the crypto's (below) and ai's ([per-module invariants](per-module-invariants.md));
  events reads `SM_SECRET_KEY` and `SM_SECRET_KEY_PREVIOUS` the same way.
- **Boot-time values** (route prefixes, `content_locales`, the media mount) are
  read from `app.state.<package>.settings` in `on_startup`, never during app
  construction (hydration is at lifespan start); mark them `json_schema_extra=_RESTART`.
- **Workers that never build the app** use
  `background_tasks.settings_for(ImagesSettings, "sm_images")` (cached ~30 s).
- **Host settings: env → database → default** (`.env` is env). `host/main.py`
  uses `merge_host_settings()`, so a `host.*` row is read at boot (#260); a field
  `.env` sets (`SM_MULTI_TENANT`, `SM_I18N_SUPPORTED_LOCALES`) can't be changed
  from the database until its line goes. Restart needed for build-time fields
  (the Settings screen marks them): tenancy, `i18n_*`, logging, `auth_provider`,
  `auth_public_paths`, request guards (`rate_limit_*`, `max_request_body_bytes`,
  `trusted_proxy`, `forwarded_host_allowlist`), CORS, `session_cookie_secure`,
  `api_*`, `openapi_public`, `db_*`. `maintenance_*`, `public_base_url`,
  `native_link_prefixes` apply per request. No settings table yet → env and
  defaults; outside `development`/`testing` a read failure fails the boot (#494).
- **Headless scripts never provision the session key.** `set_setting.py` and
  `seed_usage.py` build through `scripts/headless_settings.py` and exit "no secret
  key provisioned" rather than commit a `host.secret_key` row (a later boot would
  adopt it, signing everyone out and orphaning ai's credentials).

### Stored secrets (#351)

ai, billing, newsletter, records and events keep copies of one `core/crypto.py`
(`scripts/tests/parity_crypto.py`; vectors in
`scripts/tests/test_secret_crypto_formats.py`); change all five together. Writes
are `enc:v2:` (HKDF-SHA256, info `<package>:settings`), `enc:v1:` is read until
0.1.0, any other `enc:` is unreadable (never plaintext); test with
`crypto.is_encrypted`, not a prefix. Every copy also decrypts with
`SM_SECRET_KEY_PREVIOUS` (key or JSON list; env, else the located `.env`), the
one env read billing and records make; ai, newsletter and events read
`SM_SECRET_KEY` too. `scripts/reencrypt_secrets.py` lists the settings fields
(`reencrypt_support.TARGETS`) and events' column of every tenant's rows
(`COLUMN_TARGETS`: `events_subscription.url_enc`, the one stored secret that is
not a setting).
Signed things (sessions, links, form tokens, image tickets) are not covered:
`docs/secret-key-rotation.md`.

### Content language

**A page's language is fixed for its lifetime.** Slugs are unique per
`(tenant_id, locale, slug)` and redirects are per locale, so there is no "change
language": `POST /pages/{id}/translations` makes a sibling in the same
`translation_group`. Every slug lookup and redirect takes a locale; one that
doesn't is how `/de/p/x` serves the English page.

### Background work, releases, e2e

- **Background work** goes through `background_tasks`
  (`docs/module-layout.md#background-work`); only the
  `Background tasks (Redis + Celery worker)` job runs it non-eager
  (`scripts/bg_tasks_smoke.py`, #339).
- **Releases are lockstep.** `scripts/bump_version.py` alone edits versions and
  never rewrites framework specifiers (the framework's copy does); `scripts/tests/`
  guards it. User-visible changes go under `## <version> (unreleased)` in `CHANGELOG.md`.
- **Every e2e spec file stands alone.** CI shards by file (`--shard=i/3`, a host
  and database each, #119): seed what you need in the file; suite-wide settings go
  in `tests/e2e/start-test-server.sh`. `scripts/e2e_shards.mjs` drives
  `make e2e-parallel`. Opt-ins, each its own job and ignored by the shards:
  `E2E_MULTI_TENANT=1` (`billing-tenant`, `news-tenant`, `records-tenant`;
  `tenants.subdomain_base=localhost`, so `<org-slug>.localhost` is an org's site),
  `E2E_BILLING_USER=1` (`billing-user`, #274; `subject_mode` set before boot) and
  `E2E_NEWSLETTER=1` (`newsletter.spec.ts` and `newsletter-events.spec.ts`, non-bundle host with
  `SM_ENVIRONMENT=development`, since `testing` blanks the console under the CSP
  and the dispatch hook is absent in production; locally
  `E2E_NEWSLETTER=1 npx playwright test`).
