# CLAUDE.md

Guidance for Claude Code in this repository. See `README.md` for general
project documentation.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`. `host/` is a
development app that mounts them; it is never published.

## Rules that are easy to get wrong

**Pin policy differs by role.** Published modules depend on the framework with
*ranges* (`simple_module_core>=0.0.36,<0.1`). The host pins *exactly*
(`simple_module_hosting==0.0.38`). Never give a published module an `==` pin —
it becomes uninstallable in any host running a newer framework build.
`scripts/check_rules.py` (in `make lint` and CI) rejects one, and also any
requirement on another module of this repo (news' `pagebuilder` extra) without
a `>=` floor and a `# floor: <reason>` comment saying which change that version
first shipped. It never compares the floor with the lockstep version, so raise
the floor and its comment together when a module starts using something newer.

**Migrations live in `host/migrations/versions/`, never in a module.** Modules
ship SQLModel tables; each consuming host autogenerates its own revisions
against them. A module's first revision carries
`branch_labels = ("<module>",)` so the revision can be named
(`alembic downgrade <module>@base`). **That does not roll back only that
module.** Autogenerate chains every revision off the current head, so the
labelled revision sits on one shared history and `<module>@base` walks
everything beneath it — verified: `downgrade records@base` ran 20 downgrades
and emptied the database. Removing one module's schema in isolation needs its
tables on a real branch (`down_revision = None`), which nothing here produces
yet. Upstream #333 was closed on 2026-10-07 as a documentation correction
(framework 0.0.36, PR #403): the framework's own docs now say the label is only
a named target, and no behaviour changed, so the limitation stands.

**The history must end in exactly one head.** It is not linear: two PRs that
each add a revision off the same parent leave two heads once both land, which
breaks `make migration` ("Multiple heads are present") and makes
`make downgrade` (`-1`) roll back an arbitrary branch (#107). The fix is an
empty `alembic merge heads` revision (see `52ce60faa542`, `d3a2801784b0`);
`scripts/check_migration_heads.py` fails CI until one exists. `make migrate`
runs `upgrade heads`, which would hide a split — don't rely on it to notice.
Downgrading *through* a merge point is ambiguous with `-1`; name the parent.

**Framework tables are this host's to migrate too.** The framework's own
revisions live in its repo's host, not in the wheels, so a framework bump means
porting each new one into this history unchanged (see the `(framework 0.0.3x)`
revisions, e.g. `307543b6146a`…`b65e04cf65d7` for 0.0.37/0.0.38) and then
`alembic check` on SQLite *and* Postgres. Framework 0.0.41 added `simple_module_file_storage`,
`simple_module_sharing` and `simple_module_background_tasks` to the host's
dependencies. Their tables had never been in this history (the framework keeps
`background_tasks_task_execution` in its initial schema, which this host never
had), so `c9e3a5f1b7d2` creates it and `b5d3f08a6e17`, `e878882924e7`,
`bb906e1a1089` and `1f5985daa10b` (background_tasks), `f733c7938fd1` (sharing)
and `a625f0b7c912`, `a626b1c8d023` (users) follow, upstream ids unchanged and
chained linearly. **0.0.40 hashes bearer tokens at rest**: `a626b1c8d023`
deletes every `users_access_token` and `users_refresh_token` row, so every
session and API token is invalidated once on upgrade, and anything that stored
a raw token must keep the plaintext itself (the table holds only a digest).
0.0.42's `b31a70971001` (background_tasks resource columns) and `f5b1c3e8a207`
(`file_storage_stored_file.size_bytes` to `BIGINT`) follow the images head;
`f5b1c3e8a207` is ported **without** its upstream `("file_storage",)` branch
label, because `ca297bbf33bf` already carries it here and Alembic refuses a
label used twice — keep dropping a duplicate label when porting.
SQLModel is unpinned since 0.0.38
(framework 0.0.37+ imports its `UTCDateTime`): a bare `datetime` field is
`timestamptz` now, which is why `9d83e789a5b4` retypes the framework's
`users_refresh_token` columns on Postgres. And since 0.0.37 the soft-delete and
tenant criteria reach Core statements on `Model.__table__` (subqueries,
`INSERT … SELECT`, DML) — a Core statement that must see the trash needs
`include_deleted=True` like an ORM one.

**A page's language is fixed for its lifetime.** Slugs are unique per
`(tenant_id, locale, slug)`, and a rename records a redirect scoped to that locale.
Moving a page between languages would strand its slug in the old one and
orphan the redirect pointing at it, so there is no "change language" — there
is `POST /pages/{id}/translations`, which creates a sibling sharing a
`translation_group`. Every slug lookup and redirect takes a locale; adding one
that does not is how `/de/p/x` starts serving the English page.

**Every pagebuilder, news, records and images entry point binds a tenant (#38, #112).**
Their tables carry `MultiTenantMixin`, and the framework filters them only
while a tenant is bound — on a host with `multi_tenant` off nothing is bound
and a read is *unfiltered*. Routers get `tenancy.bind_admin`/`bind_public`,
and all modules follow one rule: single-tenant host → `"default"`; multi →
the tenant the framework resolved (`request.state.tenant_id`, the active
membership — never `user.tenant_id`, never a header a module reads itself);
none resolved → 403 `tenant_required` for admin, 404 for public. The rule is
applied per request, and a tenant already resolved upstream always wins: a
`single` detection supplies `"default"` only when nothing upstream bound one,
so a mis-detected child app fails closed — and a public answer for another
tenant is never shareable-cached (records #196; pagebuilder and news #192).
The scheduler opens one session per tenant under `tenant_context`. News has its
own copy, `news.tenancy`, and its scheduler ticks per tenant the same way;
records' is `sm_records.tenancy` (its 403 is the `{"detail","code"}` envelope,
code `tenant_required`) and images' `sm_images.core.tenancy` is a copy of it; images'
Celery tasks never run unscoped — `images.reconcile` and `images.janitor`
enumerate tenants in one narrow `all_tenants()` read and do each tenant's work
under `tenant_context`; billing reads the same `request.state.tenant_id`
through `context.billing_context`. Another module reads pagebuilder only
through `pagebuilder.contracts` (news' search calls
`search_pages`/`search_media`, #130); the caller names the tenant and the
contract pins `tenant_id` itself. A bundle section
(`pagebuilder.contracts.bundle`, #80) applies through the restore's own
session and bound tenant, and never commits or resolves a tenant itself.

**Records' website-submission routes are anonymous writes (#101).** The record
type is the trust anchor: never trust the `RecordForm` block's props —
which fields are public, the consent text and the recipients live on
`RecordType.public_submissions`. The `sm_*` system fields are written only
through the internal `system=` argument of `create_record`/`update_record`.
The routes under `/api/records/submissions/` do not use `RequiresCsrf` on
purpose (JSON, `Origin` and a signed form token instead). Every purge path
— `hard_delete_record` (which the bulk purge calls per record), emptying the
trash (`empty_trash`; both reach `_purge_ids`) and deleting the type
(`purge_type_records`) — locks the record rows and forgets their
`records_submission_delivery` claims first, through `forget_deliveries`; a
new way of deleting records must go through one of them. The retention sweep
trashes with `soft_delete_record` and then calls `hard_delete_record`.

**Never add a file under `modules/*/*/pages/` unless it is a real Inertia
page.** The page name is derived from that path by `import.meta.glob`, so a
stray `.tsx` there silently registers a new page. Extractions go to
`components/`, `hooks/`, or `utils/`. `scripts/check_rules.py` fails on any
file there that is not a `.tsx` with `export default` (exceptions go in its
`PAGES_ALLOWLIST`).

**Releases are lockstep.** One version across the repo. `scripts/bump_version.py`
is the only thing that edits versions, and it must never rewrite framework
dependency specifiers — the framework's own copy of that script does, which
would pin the framework to a version that doesn't exist. `scripts/tests/`
guards this and CI runs `--check-current`.

**`billing` commits outside a request with `finalize_session`, never
`commit()`.** Every `session_factory()` session is a `RequestSession`;
`TenantService.set_status` queues `TenantStatusChanged` and the membership-cache
invalidation on `on_commit`, which only `simple_module_db.finalize_session`
runs. A bare `commit()` in a webhook, reconcile or event handler suspends the
tenant in the database while every member's cached view still says active.
Metering writes run in their own short transaction finished with
`finalize_session`. Pass `db=` to `consume`/`record` only when the rest of the
caller's transaction is short, because the rollup row lock is held until it
commits.
Two more billing invariants: webhook payloads are never trusted for state (every
event re-fetches the subscription through `sync.resync`/`apply_snapshot`, the
one place provider state becomes local state), and response models
(`PlanOut`) must not inherit input bounds — a stored row that predates a bound
would 500 every screen listing plans. Its docs are in `modules/billing/docs/`.

**`pagebuilder`, `news`, `billing`, `ai` and `images` read no environment variables.** Their settings are
DB-backed through the framework's settings module (`register_module_settings`),
and each class drops pydantic-settings' env, `.env` and secrets sources — so
adding a field means adding it to the class, not to `.env.example`, and an
`SM_PAGEBUILDER_*` line anywhere is dead. Configure them on the Settings screen
or with `scripts/set_setting.py`. Anything the module reads while booting
(route prefixes, `content_locales`, the media mount) has to be read from
`app.state.<package>.settings` in `on_startup`, not during app construction:
hydration happens at lifespan start, so a value read earlier is the pydantic
default no matter what the database says. Mark such fields
`json_schema_extra=_RESTART` so the Settings screen says a restart is needed.
These settings are SYSTEM-scope: ai has one provider configuration and one
API key per slot for the whole deployment, shared by every tenant. ai reads
two things from the environment, both only as the framework's
`BootstrapSettings` locates `.env` (`SM_PROJECT_ROOT`, else the walk up to the
project root) — never a cwd-relative file (#124): `SM_SECRET_KEY`, for its key
encryption, and `SM_DATABASE_URL`, only when `sm_ai.contracts.consume_requests`
is called without a `session_factory` while billing is installed (it then opens
its own NullPool engine on the host database, `metering._own_factory`). Images
always passes its factory, so that fallback is for other callers. Images' workers never build the app, so they read
the same class with `background_tasks.settings_for(ImagesSettings, "sm_images")`
(DB-backed, cached about 30 s).

**A plugin registers images steps and presets from `images_extensions.py`, never
from `on_startup`.** Celery workers do not run module hooks, and a dependant's
`on_startup` runs after images' own. A package with a `simple_module` entry point
ships `images_extensions.py` with `def register(registry)`;
`sm_images.pipeline.extensions.load_extensions()` imports it in the web process
(images' `on_startup`) and in a worker (first registry read), then freezes the
registry, so a later `register_step` raises `RegistryFrozenError`. The plugin must
be installed identically in the web image and in **every** worker image: a worker
without it settles the plugin's steps as `not_installed`. Docs:
`modules/images/docs/`.

**Host settings come from the environment first, then the database.**
`host/main.py` builds its settings with the framework's
`merge_host_settings()` — what `create_app` does when given none — so a
`host.*` row written on the Settings screen or with `scripts/set_setting.py
host <field> <value>` is read at boot (#260). A bare `Settings()` reads the
environment only, so before that the rows the app is *built* from were
ignored; runtime fields were already hydrated onto `app.state` at lifespan
start. Precedence is the framework's: **env → database → default**, `.env`
counting as env. So a field `.env` sets (`SM_MULTI_TENANT`,
`SM_I18N_SUPPORTED_LOCALES` in `.env.example`) cannot be changed from the
database; delete the line first. Every host field the app is built from needs
a restart — the Settings screen marks them: tenancy (`multi_tenant`,
`tenant_header`, `default_tenant`), i18n (`i18n_*`), logging, `auth_provider`,
`auth_public_paths`, the request guards (`rate_limit_public`,
`rate_limit_authenticated`, `max_request_body_bytes`, `trusted_proxy`,
`forwarded_host_allowlist`), CORS, `session_cookie_secure`, the OpenAPI fields
(`api_*`, `openapi_public`) and the database pool (`db_*`).
`maintenance_mode`/`maintenance_message`, `public_base_url` and
`native_link_prefixes` are read per request and apply at once. A database
without the settings table yet (a fresh install) boots on env and defaults;
outside `SM_ENVIRONMENT=development`/`testing`, a connection or query failure
while reading it fails the boot instead (framework #494). The headless scripts
(`set_setting.py`, `seed_usage.py`) build their app the same way, through
`scripts/headless_settings.py`, with one difference: `merge_host_settings()`
generates and commits a `host.secret_key` row when neither env nor the
database has a key, and a one-off command must never provision the
deployment's session key (a later boot without `SM_SECRET_KEY` would adopt
it, signing everyone out and orphaning ai's encrypted credentials). So they
exit with "no secret key provisioned" instead; set `SM_SECRET_KEY` or boot
the app once.

**Run Python entry points from the repo root.** `alembic.ini` resolves its
`script_location` relative to itself and `dev-api` uses `--app-dir host`, so
the root `.env` is the single source of truth for settings regardless of the
command.

**Module layout: `docs/module-layout.md`, with images as the reference.**
A package root keeps only what something else looks up by name (`module.py`,
`models/`, `tasks.py`, `task_config.py`, `pages/`, `locales/`, `index.ts`,
`pagebuilder-blocks.ts`, plus `contracts/`, the import path other modules use).
Everything else goes in one of a few areas: `core/` (what every feature
builds on), `web/` (endpoints, schemas, services, serving), one folder per
domain (images: `ingest/`, `pipeline/`, `jobs/`, `map/`) and `ui/` for the
frontend that is not a page. Tests mirror the areas under `tests/`.
New code in any module follows it. Other modules move towards it in PRs that
contain only moves; the doc's table says how far each one has got.

**300-line cap** on every `.py` / `.ts` / `.tsx`, enforced by
`scripts/check_file_size.py`. Nothing under `modules/` is exempt. The check
also lists files at 280+ lines as a WARNING: when you touch one, split it by
responsibility rather than trimming comments until it fits (#133). A mixin
split out of a service declares what it needs from the composing class as a
`Protocol` (`pagebuilder/service/_host.py`, `news/content/_host.py`) — add a
member there before a mixin uses it; the `test_*_host.py` tests enforce it.

**Every e2e spec file stands alone.** CI shards the suite by file
(`--shard=i/3`, one host and database per shard, #119), so a spec cannot rely
on data or settings another file created. Seed what you need in the file
itself; suite-wide settings belong in `tests/e2e/start-test-server.sh`. The
`E2E (Playwright)` job merges the shards' reports and is the one status that
covers all of them.

## Local database

Local dev defaults to **SQLite** (`host/app.db`), so Postgres is optional. To
use it, set:

```
SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules
```

**Prefer the maintainer's shared `dev-services` stack when you have it.** Every
local repo shares one (PostGIS + Redis + MinIO + Adminer on the `devnet` Docker
network), started once with `make up` in `<path-to>/dev-services`. Add the
database to its `init/01-databases.sql` if it doesn't exist, and don't spin up
a per-project Postgres beside it; if 5432 is taken by an old per-project
container, stop that container rather than remapping ports.

Without that stack, one container matching CI's image is enough:

```bash
docker run -d --name smpy-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=smpy_modules postgres:16
```

Redis and Celery are used by the **images** module (framework
`background_tasks`, host pinned `==0.0.42`): `SM_REDIS_URL` points at dev-services'
Redis, and `make worker` / `worker-imports` / `worker-heavy` / `worker-gpu` /
`beat` run `host/worker.py` (`build_runner_celery`) with one queue set each.
`make dev` starts none of them. With no worker, set
`SM_BG_TASKS_TASK_ALWAYS_EAGER=true` (`.env.example`; the e2e server exports it,
plus `..._TASK_EAGER_PROPAGATES=true`) and tasks run inline. CI installs
`tippecanoe` with apt in the Python-tests and Postgres jobs. **The images
`[anonymize]` extra (onnxruntime) is never installed by default.** `make install`,
the Python-tests, repo-checks, e2e (`.github/actions/e2e-setup`) and `release`
jobs and `framework-latest` sync with `--all-extras --no-extra anonymize` (the
`quality`, `ai`, `billing` and `pagebuilder` extras are installed, `anonymize`
is not); the Postgres and frontend jobs sync no extras. The anonymize step's
default tests use a fake detector (and a fake `onnxruntime` for the wiring).
Only the weekly/manual `images-models` workflow syncs the extra, downloads the
pinned weights and runs the `real_models` tests. **No AGPL code or weights in
that extra** (user decision, 2026-10-29): runtime and both models are MIT
(YuNet faces, open-image-models YOLOv9 plates; `modules/images/NOTICE`,
`modules/images/docs/index.md`). Do not bring back torch/ultralytics or an
ultralytics-trained checkpoint, whatever its model card says.

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/path/to/simple_module_python
make unlink-framework
```

Editable-installs the framework's `core`/`db`/`hosting` into the workspace
venv and back. Neither touches a tracked file. `FRAMEWORK` has no default;
the target fails without it.

## Known deferred work

- **UI i18n — done in every module, in English and German.** All six ship
  `locales/en.json` and `locales/de.json` and route every string through
  `t()`. `scripts/check_locales.py` (in `make lint` and CI) fails when a
  translation's key tree or placeholders drift from `en.json` — add a key to
  every catalogue at once. The demo host speaks both
  (`SM_I18N_SUPPORTED_LOCALES` in `.env.example`; the `locale` cookie picks
  one, written by the framework's own `POST /i18n/set-locale`, which
  `create_app` mounts since 0.0.37 — the host's copy, `host/locale_switch.py`,
  is gone). The console chrome is German too: the framework ships the `ui`
  catalogue inside `simple_module_hosting` (German included since 0.0.38) and
  ignores any `packages/ui/locales`. `host/locales/overrides/de.json` keeps
  only the labels the host words differently, and
  `host/tests/test_ui_locales.py` fails when a framework bump leaves a `ui`
  key without German, drops a key an override names, or makes an override
  redundant. The framework modules' screens (users, settings, …) ship German
  since 0.0.38 as well.

  news, pagebuilder, ai, billing, records and images call
  `t(keys.<module>.<section>.<key>)`, with no `defaultValue` — each
  module's `utils/i18n.ts` supplies the English text from `en.json`. A
  family of keys chosen at runtime (`filters.op.<op>`) is a
  `Record<Union, string>` of `keys.…` leaves, not a template literal. The
  catalogue's namespace is the `modules/<name>` directory, not the package
  (`sm_billing` registers as `billing`) — `tests/vitest-i18n.ts` keys on the
  same name.

  **The trap, if you add a module.** The framework generates the `keys` object
  and the `t()` key union from the merged registry of every locale directory a
  host loads. Inside its own monorepo it writes them into `packages/i18n/src`.
  Here, `@simple-module-py/i18n` comes from npm, and as installed it carries
  only the framework's own namespaces. Until something regenerates it,
  `keys.<yourmodule>` does not exist and passing a literal to `t()` is a type
  error. Since 0.0.38, `smpy host gen-i18n` (upstream #449) can write every
  installed module's keys into `node_modules/@simple-module-py/i18n/src`, but
  that does not fix the problem for a published module, for two reasons. The
  copy is untracked and every `npm ci` wipes it. And `keys` is a runtime value,
  so a consuming host that bundles a module without running gen-i18n first gets
  `keys.<module>` undefined. A module therefore has to ship its own key tree,
  and so will the next module added to this repo.

  The way round it, which news established and pagebuilder copied: derive `keys`
  from the module's own `locales/en.json` at compile time (`resolveJsonModule`
  plus a mapped type), so the catalogue *is* the key tree and `tsc` rejects a
  key the JSON does not define. See `modules/news/news/utils/i18n.ts` — about
  ninety lines, and the reference implementation. Leaves are typed `string`
  rather than the literal, because the published `t()` narrows to the
  framework's union and rejects a literal outside it.

  Puck block labels cannot call a hook: a block config is a module-scope
  constant, imported before anything renders. Labels hold the *key* and are
  resolved at render — see each module's `localizeConfig.ts`. Pagebuilder's also
  recurses into `arrayFields`/`objectFields`, without which the labels inside a
  repeater's rows stay dotted keys, visible only once a row is expanded.

  Not to be confused with **content** i18n, which is done: pages and articles
  can be published in several languages. That is pagebuilder's
  `content_locales` setting and `pagebuilder.locales`, deliberately separate
  from the host's `SM_I18N_SUPPORTED_LOCALES` above — one decides what the site
  publishes, the other what the console speaks.
- **The demo host defaults to single-tenant.** Every module is tenant-aware,
  so `SM_MULTI_TENANT=true` boots with all of them enabled. The multi-tenant
  e2e specs (`billing-tenant`, `news-tenant`, `records-tenant`) are opt-in with
  `E2E_MULTI_TENANT=1` and run in their own CI job, `E2E (multi-tenant)`;
  `start-test-server.sh` sets `tenants.subdomain_base=localhost` for that run,
  so `<org-slug>.localhost` addresses an organisation's public site.
