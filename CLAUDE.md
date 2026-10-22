# CLAUDE.md

Guidance for Claude Code in this repository. See `README.md` for general
project documentation.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`. `host/` is a
development app that mounts them; it is never published.

## Rules that are easy to get wrong

**Pin policy differs by role.** Published modules depend on the framework with
*ranges* (`simple_module_core>=0.0.35,<0.1`). The host pins *exactly*
(`simple_module_hosting==0.0.36`). Never give a published module an `==` pin —
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

**A page's language is fixed for its lifetime.** Slugs are unique per
`(tenant_id, locale, slug)`, and a rename records a redirect scoped to that locale.
Moving a page between languages would strand its slug in the old one and
orphan the redirect pointing at it, so there is no "change language" — there
is `POST /pages/{id}/translations`, which creates a sibling sharing a
`translation_group`. Every slug lookup and redirect takes a locale; adding one
that does not is how `/de/p/x` starts serving the English page.

**Every pagebuilder, news and records entry point binds a tenant (#38, #112).**
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
code `tenant_required`); billing reads the same `request.state.tenant_id`
through `context.billing_context`. Another module reads pagebuilder only
through `pagebuilder.contracts` (news' search calls
`search_pages`/`search_media`, #130); the caller names the tenant and the
contract pins `tenant_id` itself.

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
Two more billing invariants: webhook payloads are never trusted for state (every
event re-fetches the subscription through `sync.resync`/`apply_snapshot`, the
one place provider state becomes local state), and response models
(`PlanOut`) must not inherit input bounds — a stored row that predates a bound
would 500 every screen listing plans. Its docs are in `modules/billing/docs/`.

**`pagebuilder`, `news`, `billing` and `ai` read no environment variables.** Their settings are
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
API key per slot for the whole deployment, shared by every tenant. The one
thing ai still reads from the environment is `SM_SECRET_KEY`, for its key
encryption, and only as the framework's `BootstrapSettings` locates `.env`
(`SM_PROJECT_ROOT`, else the walk up to the project root) — never a
cwd-relative file (#124).

**Run Python entry points from the repo root.** `alembic.ini` resolves its
`script_location` relative to itself and `dev-api` uses `--app-dir host`, so
the root `.env` is the single source of truth for settings regardless of the
command.

**300-line cap** on every `.py` / `.ts` / `.tsx`, enforced by
`scripts/check_file_size.py`. Nothing under `modules/` is exempt. The check
also lists files at 280+ lines as a WARNING: when you touch one, split it by
responsibility rather than trimming comments until it fits (#133). A mixin
split out of a service declares what it needs from the composing class as a
`Protocol` (`pagebuilder/service/_host.py`, `news/content/_host.py`) — add a
member there before a mixin uses it; the `test_*_host.py` tests enforce it.

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

This repo does not use Redis or Celery.

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/path/to/simple_module_python
make unlink-framework
```

Editable-installs the framework's `core`/`db`/`hosting` into the workspace
venv and back. Neither touches a tracked file. `FRAMEWORK` has no default;
the target fails without it.

## Known deferred work

- **UI i18n — done in every module, in English and German.** All five ship
  `locales/en.json` and `locales/de.json` and route every string through
  `t()`. `scripts/check_locales.py` (in `make lint` and CI) fails when a
  translation's key tree or placeholders drift from `en.json` — add a key to
  every catalogue at once. The demo host speaks both
  (`SM_I18N_SUPPORTED_LOCALES` in `.env.example`; the `locale` cookie picks
  one, written by `host/locale_switch.py` because framework 0.0.36 has no
  `/i18n/set-locale` route for its own switcher). The console chrome is German
  too, through `host/locales/overrides/de.json`: since 0.0.36 the framework
  ships the `ui` catalogue inside `simple_module_hosting` (English and Spanish
  only) and ignores any `packages/ui/locales`, so a host's German is an
  override, and `host/tests/test_ui_locales.py` fails when a framework bump
  adds a `ui` key it lacks. The framework modules' screens (users, settings,
  …) ship English only and fall back to it.

  news, pagebuilder, ai, billing and records call
  `t(keys.<module>.<section>.<key>)`, with no `defaultValue` — each
  module's `utils/i18n.ts` supplies the English text from `en.json`. A
  family of keys chosen at runtime (`filters.op.<op>`) is a
  `Record<Union, string>` of `keys.…` leaves, not a template literal. The
  catalogue's namespace is the `modules/<name>` directory, not the package
  (`sm_billing` registers as `billing`) — `tests/vitest-i18n.ts` keys on the
  same name.

  **The trap, if you add a module.** The framework generates the `keys` object
  and the `t()` key union into `packages/i18n/src`, from the merged registry of
  every locale directory *a host inside its own monorepo* loads. That directory
  does not exist here, and the published `@simple-module-py/i18n` carries only
  the framework's own namespaces — so `keys.<yourmodule>` does not exist and
  passing a literal to `t()` is a type error. That is a property of where the
  generator writes rather than of anything a module does wrong, and it will be
  equally true of the next module added to this repo.

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
- **`smpy_pagebuilder`** still holds the pre-port copy of this module. This
  repo is canonical; that one is frozen.
- **The demo host defaults to single-tenant.** Every module is tenant-aware,
  so `SM_MULTI_TENANT=true` boots with all of them enabled. The multi-tenant
  e2e specs (`billing-tenant`, `news-tenant`, `records-tenant`) are opt-in with
  `E2E_MULTI_TENANT=1` and run in their own CI job, `E2E (multi-tenant)`;
  `start-test-server.sh` sets `tenants.subdomain_base=localhost` for that run,
  so `<org-slug>.localhost` addresses an organisation's public site.
