# AGENTS.md

Rules for coding agents in this repository; `README.md` is the human
introduction. Where a rule has more detail, the link says where.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`; `host/` is a
development app that mounts them and is never published. The nine modules,
each with docs in `modules/<name>/docs/`: **ai**, **analytics**, **billing**,
**events**, **images**, **news**, **newsletter**, **pagebuilder**, **records**.

New code must run on **Python 3.12** (the `requires-python` floor) and **3.14**
(the Docker runtime); CI tests both. Run Python entry points (`scripts/*.py`,
`make dev-api`, and alembic as `uv run --project host alembic -c host/alembic.ini
...`, which is what `make migrate`, `migration` and `downgrade` run) from the repo root:
`host/alembic.ini` resolves `script_location` relative to itself and `dev-api`
uses `--app-dir host`, so the root `.env` is the one source of settings.

## Checks

`make lint` runs, in order:

| Step | Enforces |
| --- | --- |
| `ruff check .` | Lint incl. `S` (bandit) except `S101`, because a production `assert` only narrows a type after a real check, never validates input; tests and `scripts/` have per-file ignores, production code a line-level `# noqa: Sxxx - <reason>` |
| `basedpyright` | Basic mode over `[tool.pyright] include` only: every `contracts/` package and its cross-module callers (#338); widen it module by module. There a SQLModel column in a query goes through `sqlmodel.col()`, and a suppression is `# pyright: ignore[rule]` with its reason |
| `npx biome check .` | JS/TS lint and format |
| `make typecheck` | `tsc --noEmit` per module |
| `scripts/check_metadata.py` | Package metadata and the root pytest `testpaths` |
| `scripts/check_rules.py` | No `==` framework pin in a module; sibling requirements carry a `>=` floor and `# floor:` comment; only real pages under `pages/` |
| `scripts/check_sibling_contracts.py` | Each `<sibling>.contracts` import exists at the floor's tag; no import of a sibling's other code (needs `git fetch --tags`) |
| `scripts/moved_paths.py --check` | The 0.0.14 moved-path stubs match their tables; nothing imports an old path |
| `scripts/check_ts_imports.py` | No deep frontend import into another module (#337) |
| `scripts/check_readmes.py` | Each module README exists, is ≥500 bytes, has an H1, Install and Usage |
| `scripts/check_hardcoded_strings.py` | Permissions, roles, Inertia pages and module deps are named constants |
| `scripts/check_file_size.py` | 300-line cap; 280+ warns |
| `scripts/check_locales.py` | Each `locales/<lang>.json` matches `en.json`'s keys and placeholders |
| `scripts/check_migration_heads.py` | One migration head |
| `scripts/bump_version.py --check-current` | Every package carries the lockstep version |

Tests: `make test-py`, `make test-js`, `make e2e-bundle` (serial) or
`make e2e-parallel` (three local shards). CI (`.github/workflows/ci.yml`):
`Lint (ruff)` (ruff + basedpyright), `Lint (biome)`, `Python tests (pytest, 3.12)`
and `(pytest, 3.14)`, `Postgres (migrations + module suites)`,
`Frontend build (tsc + vite)`, `Frontend unit tests (vitest)`,
`Docker image (build + boot)`, `Background tasks (Redis + Celery worker)`,
`Repo checks (metadata, readmes, strings, file size)` (the lint scripts plus
`pytest scripts/tests`), three `E2E shard` jobs merged into `E2E (Playwright)`,
and the opt-in `E2E (multi-tenant)`, `E2E (billing per user)` and
`E2E (newsletter)`. Also: `framework-latest.yml` (nightly, every module against
the newest framework in range; red means the next bump needs work),
`images-models.yml` (weekly or manual, images' anonymize step on the real
models) and `release.yml` (`docs/releasing.md`).

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
  `/c/` and, third, events' `/events/feed/{token}.ics` (below).

### Settings and the environment

- **No module reads environment variables for its settings.** They are DB-backed
  (`register_module_settings`; `DbBackedSettings` drops env, `.env` and secrets
  sources): a field goes on the class, not `.env.example`; `SM_PAGEBUILDER_*`
  lines are dead. Set them on the Settings screen or with `scripts/set_setting.py`.
  The only env reads are the crypto's (below) and ai's (Per-module invariants);
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

## Per-module invariants

- **records, submissions (#101)** are anonymous writes: the type
  (`RecordType.public_submissions`) is the trust anchor, never the `RecordForm`
  props; `sm_*` fields are written only via `system=`; no `RequiresCsrf` on
  purpose (JSON, `Origin`, signed form token). Purges go only through
  `hard_delete_record`, `empty_trash` or `purge_type_records` (`forget_deliveries`).
  [architecture](modules/records/docs/architecture.md#public-submissions-and-system-fields),
  [API](modules/records/docs/api-reference.md#website-submissions).
- **records, secret fields** are `SealedSecret`, never `str` (captcha secret, #350;
  provider installed in `core/boot.register_settings` for headless scripts).
  [operations](modules/records/docs/operations.md#website-forms-and-newsletters).
- **records, registration**: events owns the seats, records the person; they meet
  only in `sm_events.contracts.registration` (caller's transaction, never commits).
  Lock order: records' type and row locks, the event row (`FOR SHARE`, admit only),
  counter rows in ascending id (`FOR UPDATE`), seats; contention is `SeatsBusy`. A
  registration token is records' form-token surface (the first documented
  exception). `sm_records.contracts.dated` serves events' `records:dates` under the
  caller's own access; `integrations/events/` alone imports `sm_events`
  ([registration](modules/records/docs/registration.md#for-contributors)).
- **events** ([rules](modules/events/docs/rules.md)):
  - Access goes through `core.access.POLICY`; a change to an existing event starts
    with `claim_revision`; recurrence never expands without an `until`; the API
    takes a wall clock plus an IANA zone, never UTC
    ([access](modules/events/docs/rules.md#access)).
  - FullCalendar is imported only under `ui/calendar/adapter/` (MIT packages on the
    allow-list); grid changes convert through `ui/calendar/time/zones.ts`
    ([calendar](modules/events/docs/rules.md#the-calendar-fullcalendar-7)).
  - Everything anonymous goes through `core/access/public.py` and answers "not
    here" one way; a new public route joins `tests/web/public/leaks.py`; production
    sets `public_base_url`. `contracts.cards` and the blocks' routes are the same
    projection, fetched live ([public](modules/events/docs/rules.md#the-public-surface)).
  - Private feeds and `.ics` import: one padded 404, SHA-256 tokens only, `scan.py`
    the only parser, a private item stays a draft
    ([feeds](modules/events/docs/rules.md#private-feeds-and-the-ics-import)).
  - Subscription URLs are fetched only through `feeds.subscriptions.fetch`, stored
    only as `enc:v2:` (`url_enc`), and a fetch `Policy` comes only from
    `policy.effective` ([subscriptions](modules/events/docs/rules.md#subscriptions)).
  - Reminders are at most once: claim in `events_reminder_sent`, commit, then send
    ([reminders](modules/events/docs/rules.md#reminders-are-at-most-once)).
  - Plugins register from `events_extensions.py`, never `on_startup`, installed in
    the web and every worker image; plugin settings are never secret
    ([plugins](modules/events/docs/rules.md#plugins)).
- **newsletter**:
  - HTML only from `sm_newsletter.content.render`; cards only via
    `content/integrations/` (news, pagebuilder and `sm_events.contracts.cards`; an
    event card is a snapshot of a published event of a public calendar, frozen at
    scheduling, its id never printed); writes guarded by `expected_revision` ([content](modules/newsletter/docs/content.md)).
  - Test sends go only to vouched-for addresses, under the dispatch lock and
    budget; a refusal writes no row ([test sends](modules/newsletter/docs/sending.md#test-sends)).
  - Suppressions are tenant-wide; only a double-opt-in confirmation or an admin
    lift (never `complaint`, under records' `lock_confirmation`, which every new
    unsubscribe path takes) clears one ([suppressions](modules/newsletter/docs/audience.md#suppressions)).
  - The Mailchimp import never clears or confirms a pending signup, publishes no
    events and keeps `lock_import_batch`'s lock order ([import](modules/newsletter/docs/import.md)).
  - Only the `newsletter.dispatch` beat sends, from the render snapshot;
    `/newsletter/u/`, `/o/`, `/c/` answer forged tokens like real ones
    ([sending](modules/newsletter/docs/sending.md), [tracking](modules/newsletter/docs/tracking.md)).
  - The SMTP password is written only through `PUT /api/newsletter/settings/smtp-password`
    (`newsletter.manage` and `settings.edit`); workers refuse a plaintext one
    ([secret](modules/newsletter/docs/operations.md#the-secret)). A settings write that
    changes the SMTP host, port, security or username clears it, and the generic Settings
    screen refuses newsletter writes ([settings](modules/newsletter/docs/index.md#settings)).
- **billing commits outside a request with `finalize_session`, never
  `commit()`** (`tests/core/test_commit_sites.py`, empty allow-list since #340;
  [transactions](modules/billing/docs/architecture.md#transactions--the-rule-that-bites)).
  State comes only from `sync.resync`/`apply_snapshot`, never a webhook payload;
  `PlanOut` never inherits input bounds ([architecture](modules/billing/docs/architecture.md)).
  `subject_mode = user` is restart-only and refused on a multi-tenant host; images
  replays the subject recorded per hold ([subjects](modules/billing/docs/subjects.md)).
- **images**: plugins register from `images_extensions.py`, never `on_startup`,
  installed identically in the web and every worker image
  ([plugins](modules/images/docs/writing-a-plugin.md#registration)). `[anonymize]`
  is never installed by default (its tests use a fake detector; only
  `images-models.yml` runs the real ones) and has no AGPL code or weights (user
  decision, 2026-10-29: no torch, ultralytics or ultralytics-trained checkpoint;
  [licences](modules/images/docs/index.md#anonymize-models-and-licences)).
- **ai** is SYSTEM-scope (one provider config and key per slot for all tenants)
  and reads `SM_SECRET_KEY`, `SM_SECRET_KEY_PREVIOUS` and, for `consume_requests`
  without a `session_factory` while billing is installed, `SM_DATABASE_URL`, as
  `BootstrapSettings` locates `.env`, never cwd-relative (#124;
  [settings](modules/ai/docs/operations.md#settings)).

## Local setup

- **Install**: `make install` syncs `--all-extras --no-extra anonymize`, like the
  CI Python, lint, repo-checks, e2e and release jobs and `framework-latest`;
  the Postgres, frontend and background-tasks jobs sync no extras. CI apt-installs `tippecanoe`.
- **Database**: SQLite (`host/app.db`) by default; Postgres with
  `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules`.
  Prefer the shared `dev-services` stack (PostGIS, Redis, MinIO, Adminer on
  `devnet`; `make up` there; add the database to its `init/01-databases.sql`), no
  per-project Postgres beside it (stop an old one on 5432, don't remap). Without
  it: `docker run -d --name smpy-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=smpy_modules postgres:16`.
- **Workers**: images, newsletter and events use Redis/Celery. `make worker`
  (the `images`, `newsletter`, `events` and `celery` queues), `worker-imports`,
  `worker-heavy`, `worker-gpu` and `beat` run `host/worker.py`
  (`build_runner_celery`), one queue set each; `make dev` starts none. Without
  one, `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` (e2e adds `..._EAGER_PROPAGATES=true`).
- **Tenancy**: the demo host is single-tenant; `SM_MULTI_TENANT=true` boots every
  module multi-tenant.

## Working against an unreleased framework

`make link-framework FRAMEWORK=/path/to/simple_module_python` editable-installs
its `core`/`db`/`hosting` plus `FRAMEWORK_MODULES` (default `branding`) into the
venv; `make unlink-framework` reverts. Neither touches a tracked file;
`FRAMEWORK` has no default.

## i18n

- **Console UI is English and German in all nine modules**: `locales/en.json` and
  `de.json`, every string through `t(keys.<module>.<section>.<key>)`, no
  `defaultValue`. Add a key to every catalogue at once. A runtime-chosen family
  (`filters.op.<op>`) is a `Record<Union, string>` of `keys.…` leaves. The
  namespace is the `modules/<name>` directory (`sm_billing` is `billing`), as in
  `tests/vitest-i18n.ts`.
- **Host chrome**: the framework ships the `ui` catalogue (German since 0.0.38)
  and `POST /i18n/set-locale` (`locale` cookie). `host/locales/overrides/de.json`
  keeps only labels the host words differently; `host/tests/test_ui_locales.py`
  fails on an untranslated `ui` key or a vanished or redundant override.
- **The trap when adding a module**: npm's `@simple-module-py/i18n` has only the
  framework's namespaces, so `keys.<yourmodule>` does not exist, and
  `smpy host gen-i18n` writes into `node_modules` (wiped by `npm ci`; a consuming
  host lacks the runtime `keys`). Derive `keys` from the module's own `en.json`
  at compile time (`resolveJsonModule` plus a mapped type, leaves typed `string`);
  reference: `modules/news/news/ui/utils/i18n.ts` (about 180 lines).
- **Puck block labels** hold the *key*, resolved at render (each module's
  `localizeConfig.ts`; pagebuilder's recurses into `arrayFields`/`objectFields`).
- **Content i18n** is pagebuilder's `content_locales` (what the site publishes),
  separate from `SM_I18N_SUPPORTED_LOCALES` (what the console speaks).

## Pointers

- `SECURITY.md` (reporting, scope); `CHANGELOG.md` (lockstep, a
  `## <version> (unreleased)` section).
- `docs/module-layout.md`, `docs/adding-a-module.md`, `docs/releasing.md`,
  `docs/secret-key-rotation.md`, `host/migrations/README.md`.
- History, not current rules: `docs/plans/`, `docs/superpowers/` and dated
  `*-20YY-MM-DD.md` reports. Where one disagrees with this file or a module doc,
  this file and the module doc win.
