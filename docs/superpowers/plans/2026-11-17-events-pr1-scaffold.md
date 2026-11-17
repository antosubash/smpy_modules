# Events PR 1: scaffold, tenancy, settings, calendars with sharing. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `modules/events` (`simple_module_events`, package `sm_events`) wired into the workspace and host. It carries the tables of PRs 1 and 2 in one labelled migration, DB-backed settings, a tenancy copy, one access policy for calendars, `events.calendar` sharing, the calendars and categories API, and the Calendars and Categories screens.

**Architecture:** The module follows `docs/module-layout.md`. `core/` holds constants, errors, settings, tenancy (a copy of newsletter's copy of images'), the request-context middleware (a copy of images') and `access/` (the one policy every later read goes through). `models/` declares all seven tables. `calendar/` holds the calendar and category services. `web/` holds the routers, schemas, views and menu. `ui/` holds the frontend. Sharing reuses the framework's `sharing` module exactly as images does: a resource type with a tenancy-applying loader, plus an owner-or-manager share-candidates picker. Events, texts, overrides, revisions and redirects get models now and behaviour in PR 2.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async, Alembic, the framework's `sharing`, `settings` and `inertia` modules, pytest (SQLite; Postgres opt-in via `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, vitest (happy-dom), TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md` (Delivery row 1; Data model; Access; Tenancy; Settings; Layout). Precedent plan: `docs/superpowers/plans/2026-11-03-newsletter-pr2-scaffold.md` (commit `30fefb84`).

## Rulings

- **All seven tables ship in one revision** (`events_calendar`, `events_event`, `events_event_text`, `events_occurrence_override`, `events_category`, `events_revision`, `events_redirect`), labelled `("events",)`. PR 2 adds behaviour and no migration. A column PR 2 finds missing goes in a normal follow-up revision.
- **Statuses, kinds and visibility are `VARCHAR` with Python constants, never a Postgres enum.** This follows newsletter's ruling, not images' `SAEnum`: adding a value needs no migration and no enum drop on downgrade. `Visibility(StrEnum)` (`private`, `internal`, `public`) is the Python type. Pydantic validates the API input, and the column is `str` with `max_length=16`.
- **Primary keys.** `events_calendar`, `events_event` and `events_category` use a client-generated UUID (images' `pk_uuid`, `modules/images/sm_images/models/_cols.py:17-19`): these ids appear in URLs and in `ResourceShare.resource_id`. The other four tables use a big-int PK (newsletter's `big_pk`).
- **Every tenant-scoped unique index leads with `tenant_id`.** Slugs stay unique across the trash, so a restore never collides (images' rule, `modules/images/sm_images/web/services/collections.py:41-43`).
- **No `contracts/`, `tasks.py` or `task_config.py` in PR 1**, and no `simple_module_background_tasks` dependency. The first task (`events.publish_due`) and the first contract both arrive with PR 2. So the Makefile worker queues, the `ci.yml` bg-tasks queue list and the root pyright `include` stay untouched.
- **Creating a calendar needs `events.edit`, and the caller becomes its owner.** `events.manage` can act on every calendar. The spec lists "calendars" under `events.manage`, but it also has owners who are not managers ("Sharing, visibility and deleting a calendar are the owner's or `events.manage`'s"). Letting `events.edit` holders create their own `private` calendars is what makes those owners exist. This is confirmed in the rulings below.
- **The policy needs `events.view`.** A signed-in principal without `events.view` (and without `events.manage`) gets exactly what an anonymous one gets: `public` calendars, view only. That covers an owner or a share holder who lost the permission too. Without this rule, the framework's sharing router (which only needs `sharing.share`) would let such a user read the calendar.
- **Owner and edit-share holders write events without holding `events.edit`; everyone else needs it.** This follows the spec's Access text literally. `events.edit` grants writing only on `internal` and `public` calendars. Calendar *metadata* (name, slug, colour, description, timezone) is edited by the owner, an edit share holder or `events.manage`, never through `events.edit` on an internal calendar.
- **Calendars have no `expected_revision`.** Their metadata is edited in a form, rarely, and never by a drag, so the last write wins. Events carry `revision` and the 409 `stale` guard from PR 2.
- **Errors use the `{"detail","code"}` envelope** for every error the module raises. FastAPI's own request-validation 422 keeps its standard shape, as in images and newsletter. Timezone, slug and colour are checked by pydantic validators, so a bad value is a plain 422.
- **Categories are in PR 1** (service, API and screen). They need nothing from events, and PR 2's editor needs them.
- **`/admin/events/` redirects (303) to `/admin/events/calendars` until PR 3** replaces it with the Calendar view. The menu has two entries, Calendars (`events.view`) and Categories (`events.view` and `events.manage`).
- **Settings in PR 1 are only what PR 1 reads:** `default_timezone` and `content_locales` (restart-only). `public_prefix` comes with PR 4, the reminder fields with PR 8, `import_max_bytes` with PR 5 and `subscription_refresh_minutes` with PR 10. As newsletter does, settings carry no validators (a class that does not construct is replaced with *all* defaults). `core.timezones.effective(name)` falls back to `"UTC"` for a stored name it does not know and logs one warning per name.

## Rulings on the open points (2026-11-17)

1. **Creating a calendar needs `events.edit`**, as ruled above. The spec's Access section now says so.
2. **Owners and edit-share holders write events without `events.edit`**, as ruled above.
3. **A calendar's slug can be renamed freely in PR 1.** Nothing public uses it yet. PR 4, which adds `/events/c/{calendar}`, also adds calendar slug redirects.
4. **`events.manage` can transfer ownership.** Add `PUT /api/events/calendars/{id}/owner` to Task 7: `events.manage` only, body `{owner_id}`, the new owner must be an active member of the bound tenant (the same directory and membership check as the share picker in Task 8; 422 `owner_not_allowed` otherwise). The Calendars screen shows the action to managers only (Task 11).
5. Newsletter's absence from the host test lists is a follow-up issue, not this PR.
6. Re-check framework floors if #405 has landed.
7. The duplicated share dialog goes upstream as a framework issue; copy images' here.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-module` (branch `feat/events-pr1-scaffold`). Run Python entry points from its root. Run module tests from the module directory: `cd modules/events && uv run pytest …`.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, distribution `simple_module_events`, npm `@simple-module-py/events`, locale namespace `events`, `MODULE_NAME = "Events"`, API prefix `/api/events`, view prefix `/admin/events`, table prefix `events_`, resource type `events.calendar`.
- Version `0.0.15` in `pyproject.toml` and `package.json`. Check with `uv run python scripts/bump_version.py --check-current` and use whatever it reports.
- Pins: framework deps are ranges, never `==`: `simple_module_core`, `_db`, `_hosting`, `_inertia` and `_settings` at `>=0.0.44,<0.1`, and `simple_module_sharing>=0.0.44,<0.1  # floor: sharing.core.policy path first shipped in 0.0.44` (images' line, `modules/images/pyproject.toml:19`). Write `# floor:` comments wherever images and newsletter have them. If the framework bump (#405) has landed when you start, raise each floor to the release that first shipped the path you import, and update its comment too.
- Settings: `DbBackedSettings`, with no env, `.env` or secrets source, registered with `register_module_settings`, SYSTEM scope. Any field read at boot is marked `json_schema_extra=_RESTART`.
- Every table carries `MultiTenantMixin` and sits behind the fail-closed guard. Module code pins `tenant_id` wherever it uses Core statements or `all_tenants()`.
- 300-line cap per `.py`/`.ts`/`.tsx`. Keep every file under 280 lines (`scripts/check_file_size.py` warns from 280).
- No literal permission, page or module-name strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`). Use `_PAGE_*`, `PERM_*` and `_MODULE_*`.
- Only real Inertia pages (`.tsx` with `export default`) under `sm_events/pages/`.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`). The UI calls `t(keys.events.…)`, with no literals.
- Commits: one per task, conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **A user who lost `events.view` but still owns or is shared a private calendar** must not see it in the API, the policy filter or the framework's `/api/sharing/shares` list. Covered by the truth table in Task 6 (`O-` and `SV-` rows) and by `test_share_list_needs_events_view` in Task 8.
2. **The sharing router on a single-tenant host binds no tenant.** Granting a share there must work, a calendar id from another tenant must be a 404, and a multi-tenant request without a tenant must be a 403. Covered by Task 6 (`test_loader_*`) and by Task 8's end-to-end grant through `/api/sharing/shares`.
3. **The share picker as a user directory.** With a directory installed, a `q` shorter than 3 trimmed characters returns `[]`, members of other tenants are never offered, and an edit-share holder gets 403. Covered by Task 8.
4. **Existence leaks.** A stranger gets 404 on GET, PATCH, visibility, DELETE and restore of a private calendar. A view-share holder gets 403 on PATCH (because they can see it), and an edit-share holder gets 403 `owner_required` on visibility and DELETE. Covered by Task 7 (`test_stranger_sees_404_everywhere`, `test_share_holder_403s`).
5. **Slug collisions.** An explicit slug held by a *trashed* calendar returns 409 `slug_taken`. Two calendars named "Team" get distinct derived slugs. An insert that loses a race on the unique index returns 409, not 500. Covered by Task 7 (`test_slug_*`).

---

### Task 1: Package skeleton, workspace wiring, permissions

**Files:**
- Create: `modules/events/pyproject.toml`, `package.json`, `tsconfig.json`, `README.md`, `NOTICE`, `docs/index.md`
- Create: `modules/events/sm_events/__init__.py` (docstring only), `sm_events/module.py`, `sm_events/core/__init__.py` (docstring), `sm_events/core/constants.py`, `sm_events/locales/en.json`, `sm_events/locales/de.json`
- Create: `modules/events/tests/__init__.py`, `tests/conftest.py`, `tests/pg_support.py`, `tests/core/__init__.py`, `tests/core/test_module_boot.py`
- Modify: `pyproject.toml` (`testpaths`, lines 131-142: add `"modules/events/tests"` in sorted position), `host/pyproject.toml` (add `"simple_module_events",` after newsletter at line 24, and `[tool.uv.sources.simple_module_events] workspace = true` after line 51), `uv.lock`, `package-lock.json`

**Interfaces:**
- Produces `sm_events.core.constants` (modelled on `modules/newsletter/sm_newsletter/core/constants.py:5-51`):

```python
PACKAGE = "sm_events"; MODULE_NAME = "Events"; DISTRIBUTION = "simple_module_events"
LOCALE_NAMESPACE = "events"; BASE_NAME = "events"
ROUTE_PREFIX_API = "/api/events"; VIEW_PREFIX = "/admin/events"
PERM_GROUP = MODULE_NAME; PERM_GROUP_KEY = "events.permission_group"
PERM_VIEW = "events.view"; PERM_EDIT = "events.edit"; PERM_PUBLISH = "events.publish"; PERM_MANAGE = "events.manage"
PERMISSIONS = (PERM_VIEW, PERM_EDIT, PERM_PUBLISH, PERM_MANAGE)
_MODULE_SETTINGS = "Settings"; _MODULE_SHARING = "Sharing"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_SHARING)
TENANT_REQUIRED_CODE = "tenant_required"; NOT_FOUND_DETAIL = "Not found"
```

  Later tasks add their own constants to this file; each task's Interfaces block lists them.
- Produces `sm_events.module.EventsModule(ModuleBase)`. `meta` is newsletter's (`modules/newsletter/sm_newsletter/module.py:36-45`): version from `importlib.metadata.version(DISTRIBUTION)`, `requires_framework=">=1.0,<2.0"`. `__init__` sets `self.settings = None`. Add `register_permissions` (`add_group(PERM_GROUP, list(PERMISSIONS), label_key=PERM_GROUP_KEY)`) and `locale_dirs()` (`{LOCALE_NAMESPACE: <package>/locales}`), as newsletter's lines 178-185 do.
- `pyproject.toml`: newsletter's (`modules/newsletter/pyproject.toml`) with `sm_events` substituted. Description: `"Calendars and events for SimpleModule hosts: timezone-aware and recurring events, shareable calendars, public pages and ICS feeds"`. Keywords: `["simple-module", "events", "calendar"]`. Dependencies are listed under Global Constraints, plus `pydantic-settings>=2.0`. The `dev` extra is `pytest>=8.0`, `pytest-asyncio>=0.24`, `simple_module_test>=0.0.44,<0.1`. Entry point `[project.entry-points.simple_module] events = "sm_events.module:EventsModule"`. Copy the same wheel `exclude` list, `artifacts`, `force-include` and sdist block. `[tool.pytest.ini_options]` gets `asyncio_mode = "auto"` and the `unbound_tenant` marker. There is **no** `[tool.uv.sources]` table: no sibling module is a dependency.
- `package.json`: `"name": "@simple-module-py/events"`, `"version": "0.0.15"`, `"private": true`, `"exports": {".": "./sm_events/index.ts"}`. peerDependencies are images' minus `@puckeditor/core`, the pagebuilder entry and its `peerDependenciesMeta`: `@inertiajs/react`, `@simple-module-py/i18n`, `@simple-module-py/ui >=0.0.38`, `react`, `react-dom`, `sonner`. devDependencies: `@simple-module-py/tsconfig`. `tsconfig.json` is newsletter's with `sm_events` substituted.
- Locales: `{"permission_group": "Events"}` in English and `{"permission_group": "Veranstaltungen"}` in German.
- `tests/pg_support.py`: a copy of `modules/images/tests/pg_support.py`, `_extra_metadata()` included. The access policy's `EXISTS` names sharing's table, so sharing's metadata (and permissions', when installed) is always included. `make_db_state` imports `sm_events.models.Base` lazily, because that module only exists from Task 5. `tests/conftest.py` gets newsletter's `_default_tenant` (bound with `simple_module_db.tenant_context("default")` until Task 3 swaps in `sm_events.core.tenancy.tenant_scope`) and `_arm_database_reset` (`modules/newsletter/tests/conftest.py:26-66`). Do not copy newsletter's crypto, outbox or records fixtures.

- [ ] **Step 1: Write the failing tests** in `tests/core/test_module_boot.py`:
  - `test_module_registers_permissions`: `set(registry.all_permissions) == {"events.view","events.edit","events.publish","events.manage"}`, and the single group has `label_key == "events.permission_group"`.
  - `test_locale_dir_is_the_namespace`: `EventsModule().locale_dirs()` has key `"events"`, and that folder holds `en.json` and `de.json`.
  - `test_meta`: `EventsModule.meta.name == "Events"`, `route_prefix == "/api/events"`, `view_prefix == "/admin/events"`, `set(depends_on) == {"Settings", "Sharing"}`.
- [ ] **Step 2: Run them to see them fail.** `~/.claude/bin/wait-for-headroom`, then `uv sync --all-packages --all-extras --no-extra anonymize` from the root, then `cd modules/events && uv run pytest -q tests/core/test_module_boot.py`. Expected: `ModuleNotFoundError: sm_events`.
- [ ] **Step 3: Implement** the files above. The README must pass `scripts/check_readmes.py` (an H1, at least 500 bytes, "Install" and "Usage" sections). Write it now with what the module does, the permission list and "status: PR 1 of 10". Task 13 completes it. `docs/index.md` gets a status table with the spec's ten Delivery rows (row 1 "in progress") and a link to the spec. `NOTICE`: `Copyright (c) Anto Subash. Licensed under the MIT License.` Run `npm install` at the root so `package-lock.json` gains the workspace entry.
- [ ] **Step 4: Run** the same pytest command (passes), then from the root `uv run python scripts/check_metadata.py`, `scripts/check_readmes.py`, `scripts/check_rules.py`, `scripts/check_locales.py`, `scripts/check_hardcoded_strings.py` and `scripts/bump_version.py --check-current`. All pass.
- [ ] **Step 5: Commit** `feat(events): module skeleton, workspace wiring and permissions` with every file above, plus `uv.lock` and `package-lock.json`.

### Task 2: Frontend i18n surface

**Files:**
- Create: `sm_events/index.ts`, `sm_events/ui/utils/i18n.ts`, `sm_events/ui/utils/i18n.test.ts`

**Interfaces:**
- `ui/utils/i18n.ts` is a copy of `modules/newsletter/sm_newsletter/ui/utils/i18n.ts` with `NAMESPACE = 'events'` (line 34) and the module names in the doc comment changed. It exports `keys`, `translate`, `useT` and `Translate`; `TranslateParams` is private. `index.ts` holds a doc comment ("the public TS surface; the `Calendar` component arrives in PR 3") and `export {};`.

- [ ] **Step 1: Write the failing test** `i18n.test.ts`: `keys.events.permission_group === 'events.permission_group'`, and `translate('events.permission_group') === 'Events'`.
- [ ] **Step 2: Run it to see it fail.** `~/.claude/bin/wait-for-headroom`, then `npx vitest run modules/events`. Expected: cannot resolve `./i18n`.
- [ ] **Step 3: Implement** both files.
- [ ] **Step 4: Run** `npx vitest run modules/events`, `npx tsc --noEmit -p modules/events/tsconfig.json` and `npx biome check modules/events`. All pass.
- [ ] **Step 5: Commit** `feat(events): i18n key tree and TS entry point`.

### Task 3: Tenancy, errors and the request context

**Files:**
- Create: `sm_events/core/tenancy/__init__.py`, `core/tenancy/_mode.py`, `core/tenancy/_guard.py`. These are copies of `modules/newsletter/sm_newsletter/core/tenancy/{__init__,_mode,_guard}.py` with `sm_newsletter`/`newsletter` changed to `sm_events`/`events`, `ALL_TENANTS = "events_all_tenants"` (newsletter line 88), `_UPSTREAM_ATTR = "events_tenant_from_request"` (line 213) and newsletter's wording in the `TenantRequired` message changed.
- Create: `sm_events/core/tenancy/request_context.py`, a copy of `modules/images/sm_images/core/tenancy/request_context.py` with the contextvar named `sm_events_request_scope`.
- Create: `sm_events/core/errors.py`
- Create: `tests/core/tenancy/__init__.py`, `tests/core/tenancy/test_tenancy.py`, `tests/core/tenancy/test_request_context.py`
- Modify: `scripts/tests/parity_tenancy.py`. Add `EVENTS = "modules/events/sm_events"` after line 30 and a `Copy` for events next to newsletter's in four families: "tenancy mode detection: records" (line 55, `{"logger": "_log"}`), "tenancy guard" (line 147, `{"sm_events": "MODULE", "_sm_events_tenant_guard": "_MODULE_tenant_guard"}`), "tenancy guard entry points" (line 179, `{"sm_events": "MODULE", "events_all_tenants": "MODULE_all_tenants"}`) and "tenancy binding: records" (line 192, `{"_resolved": "upstream_tenant"}`). Extend the `bind_public` differ text (line 199) to "Records', images', newsletter's and events' public 404…". In the module docstring, "five modules" (line 14) becomes "six", and "records, images and newsletter" (line 18) gains "and events".
- Modify: `scripts/tests/parity_families.py`. Add `Copy("modules/events/tests/pg_support.py")` to "test scaffolding: Postgres opt-in" (line 202), and add a new family `"request context"` with `Copy("modules/images/sm_images/core/tenancy/request_context.py", {"sm_images": "MODULE"})` and `Copy("modules/events/sm_events/core/tenancy/request_context.py", {"sm_events": "MODULE"})`, `shared=("RequestContextMiddleware", "current_request")`.
- Modify: `host/tests/test_tenancy_parity.py` (lines 14-37): import `sm_events.core.tenancy` and `sm_events.core.tenancy._mode`, then add `"events"` to `_DETECTORS` and `_RESOLVERS`.
- Modify: `tests/conftest.py`: `_default_tenant` now binds with `sm_events.core.tenancy.tenant_scope(DEFAULT_TENANT)`.

**Interfaces:**
- `sm_events.core.errors` is modelled on `modules/images/sm_images/core/errors.py:22-60`: `EventsError(Exception)` with `status_code: int`, `code: str` and `__init__(detail, code=None)`. Subclasses: `NotFound` (404, `not_found`), `Forbidden` (403, `forbidden`), `OwnerRequired(Forbidden)` (code `owner_required`), `TenantRequired(Forbidden)` (code `tenant_required`), `Conflict` (409), `SlugTaken(Conflict)` (code `slug_taken`), `Invalid` (422, `invalid`), `UnknownLocale(Invalid)` (code `unknown_locale`), `ServiceUnavailable` (503). `install_exception_handlers(app)` renders `{"detail": exc.detail, "code": exc.code}` with `exc.status_code`.
- `sm_events.core.tenancy` exports what newsletter's does: `DEFAULT_TENANT`, `TenancyMode`, `TenantUnbound`, `valid_tenant`, `tenant_scope`, `bound_tenant`, `resolve_admin`, `resolve_public`, `bind_admin`, `bind_public`, `all_tenants(stmt)`, `install_guard`, `configure`, `mode_of`, `request_mode`, `view_props`, `note_tenant_source`, `tenant_from_request`.
- `sm_events.core.tenancy.request_context`: `RequestContextMiddleware`, `current_request() -> Request | None`.

- [ ] **Step 1: Write the failing tests.** Port newsletter's `tests/core/tenancy/test_tenancy.py` with the names changed: `test_scope_refuses_a_second_tenant`, `test_invalid_tenant_refused`, `test_admin_single_mode_binds_default`, `test_admin_multi_without_tenant_is_403` (body `{"detail": …, "code": "tenant_required"}`), `test_public_without_tenant_is_none` and `test_upstream_tenant_wins_in_single_mode`. Add `test_guard_refuses_unbound_orm_read` (`unbound_tenant`): with `install_guard` applied to a session class, a `select` of any `events_` model raises `TenantUnbound`, and the same select wrapped in `all_tenants()` runs. This one depends on Task 5's models: write it now and mark it `pytest.mark.skip(reason="models in Task 5")`, then remove the skip in Task 5. `test_request_context.py::test_current_request_inside_and_outside`: inside an app with the middleware, an endpoint sees `current_request().url.path`, and outside a request the result is `None`.
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/core/tenancy`. Expected: `ModuleNotFoundError: sm_events.core.tenancy`.
- [ ] **Step 3: Implement** the copies and `errors.py`.
- [ ] **Step 4: Run** the same command (passes), then from the root `uv run pytest -q scripts/tests/test_helper_parity.py host/tests/test_tenancy_parity.py` (passes).
- [ ] **Step 5: Commit** `feat(events): tenancy copy, request context and error envelope`.

### Task 4: Settings and the services container

**Files:**
- Create: `sm_events/core/settings/__init__.py` (`EventsSettings`), `sm_events/core/services.py`, `sm_events/core/timezones.py`
- Modify: `sm_events/module.py` (`register_settings`, `register_exception_handlers`, `on_startup`)
- Test: `tests/core/test_settings.py`, `tests/core/test_timezones.py`

**Interfaces:**
- `EventsSettings(DbBackedSettings)` with `model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)`. Give every field an attribute docstring (`modules/newsletter/sm_newsletter/core/settings/__init__.py:28-60`). `_RESTART = {"requires_restart": True}` (`modules/news/news/core/settings.py:33`).

| field | type | default | restart |
|---|---|---|---|
| `default_timezone` | `str` | `"UTC"` | no |
| `content_locales` | `tuple[str, ...]` | `("en",)` | yes (the first is the default language; PR 2's slugs and PR 4's routes read it) |

- `core/timezones.py`: `def is_known(name: str) -> bool` (membership in `zoneinfo.available_timezones()`, cached once), and `def effective(name: str | None) -> str` (the name when known, else `"UTC"` with one `logger.warning` per unknown name).
- `EventsServices`: a dataclass with `settings: EventsSettings`. `EventsModule.register_settings(app)` calls `register_module_settings(app, PACKAGE, EventsSettings, lambda d: EventsServices(settings=self.settings or d))` with no `manage_url` (images' `module.py:60-75`). `register_exception_handlers` calls `install_exception_handlers`. `on_startup` calls `tenancy.configure(app)` and then `tenancy.install_guard(...)` when the session class is present (newsletter's `module.py:166-176`, without its public routes).

- [ ] **Step 1: Write the failing tests:**
  - `test_defaults`: `default_timezone == "UTC"` and `content_locales == ("en",)`.
  - `test_settings_ignore_env`: with `SM_EVENTS_DEFAULT_TIMEZONE=Europe/Vienna` and `DEFAULT_TIMEZONE=Europe/Vienna` set, `EventsSettings().default_timezone == "UTC"`.
  - `test_restart_fields`: exactly `{"content_locales"}` carries `requires_restart`.
  - `test_register_settings_mounts_services`: on a bare `FastAPI()` with a `ModuleSettingsRegistry` (as in images' `tests/core/test_module_boot.py`), `app.state.sm_events.settings` is an `EventsSettings`.
  - `test_timezones.py`: `is_known("Europe/Vienna")`; `not is_known("Mars/Base")`, `not is_known("")` and `not is_known("europe/vienna")` (case matters); `effective("Mars/Base") == "UTC"` logs exactly one warning across two calls (`caplog`).
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/core/test_settings.py tests/core/test_timezones.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command: passes.
- [ ] **Step 5: Commit** `feat(events): DB-backed settings`.

### Task 5: Models for PRs 1 and 2, and the migration

**Files:**
- Create: `sm_events/models/__init__.py` (imports every table, `__all__`), `models/_base.py` (newsletter's, `Base = create_module_base(BASE_NAME)`), `models/_cols.py` (newsletter's `big_pk`, `fk`, `dt_col` and `json_col` from `modules/newsletter/sm_newsletter/models/_cols.py:19-58`, plus images' `pk_uuid` and `fk_uuid` from `modules/images/sm_images/models/_cols.py:17-30`), `models/enums.py`, `models/calendar.py`, `models/category.py`, `models/event.py`, `models/event_text.py`, `models/occurrence_override.py`, `models/revision.py`, `models/redirect.py`
- Create: `sm_events/core/clock.py` (`utcnow() -> datetime`, aware UTC)
- Create: `host/migrations/versions/<rev>_add_events.py` (autogenerated)
- Create: `host/tests/test_events_wiring.py` (modelled on `host/tests/test_newsletter_wiring.py:10-34`)
- Modify: `tests/conftest.py` (`db_state` fixture: `await make_db_state()`, disposed afterwards; `db` fixture: one session from it), and remove the skip from Task 3's guard test.
- Test: `tests/models/__init__.py`, `tests/models/test_models.py`

**Interfaces:**
- The generated revision is `b8e1d0783868_add_events.py`, with `revision = "b8e1d0783868"`, `down_revision = "541bfbe29a28"` and `branch_labels = ("events",)`.
- `models/enums.py`: `class Visibility(StrEnum): PRIVATE="private"; INTERNAL="internal"; PUBLIC="public"`. Plus the tuples that PR 2 validates against: `EVENT_STATUSES = ("draft", "in_review", "published")`, `ATTENDANCE_MODES = ("in_person", "online", "hybrid")`, `OVERRIDE_KINDS = ("skipped", "cancelled", "moved")`, `DEFAULT_EVENT_TYPE = "event"`.
- Constants added to `core/constants.py`: `SLUG_MAX = 80`, `SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"`, `TEXT_SLUG_MAX = 200`, `TZ_MAX = 64`, `LOCALE_MAX = 16`, `COLOR_PATTERN = r"^#[0-9a-f]{6}$"`, `DEFAULT_COLOR = "#2563eb"`.
- Tables. All are `Base, MultiTenantMixin, table=True`. "Audit" means `AuditMixin` and "soft" means `SoftDeleteMixin` (`created_at`, `updated_at`, `created_by`, `updated_by`, `is_deleted`, `deleted_at` and `deleted_by` come from `simple_module_db.mixins`). Datetimes use `AwareDateTime`, stored UTC (`dt_required` for caller-supplied times; `dt_col` for optional times or creation timestamps). A column is NOT NULL unless marked nullable. Module-owned columns have no `server_default`; inherited `AuditMixin.created_at` keeps the framework's `CURRENT_TIMESTAMP` server default.

  | Table (class) | Columns | Constraints and indexes |
  |---|---|---|
  | `events_calendar` (`Calendar`, audit, soft) | `id` UUID PK; `slug` str(80); `name` str(200); `color` str(7) default `DEFAULT_COLOR`; `description` str(2000) nullable; `visibility` str(16) default `"private"`; `owner_id` str(64), indexed; `default_timezone` str(64) default `"UTC"`; `sources` JSON list default `[]` (plugin source ids only; the built-in `events` source is always on and never listed) | unique `uq_events_calendar_tenant_slug (tenant_id, slug)`; index `ix_events_calendar_tenant_visibility (tenant_id, visibility)` |
  | `events_category` (`Category`, audit) | `id` UUID PK; `slug` str(80); `names` JSON dict `{locale: name}` default `{}`; `color` str(7) nullable | unique `uq_events_category_tenant_slug (tenant_id, slug)` |
  | `events_event` (`Event`, audit, soft) | `id` UUID PK; `uid` str(255); `calendar_id` UUID FK `events_calendar.id` `ondelete="CASCADE"`; `parent_id` UUID FK `events_event.id` `ondelete="CASCADE"`, nullable, indexed; `type` str(64) default `"event"`; `status` str(16) default `"draft"`; `cancelled` bool default False; `all_day` bool default False; `starts_at`, `ends_at` datetime; `timezone` str(64); `rrule` str(1000) nullable; `recurrence_until` datetime nullable; `attendance_mode` str(16) default `"in_person"`; `venue_name` str(200) nullable; `address` str(500) nullable; `online_url` str(2048) nullable; `latitude`, `longitude` float nullable; `category_id` UUID FK `events_category.id` `ondelete="SET NULL"`, nullable, indexed; `organiser` str(200) nullable; `image` str(2048) nullable; `registration_url` str(2048) nullable; `extra` JSON dict default `{}`; `revision` int default 1; `publish_at`, `published_at` datetime nullable | unique `uq_events_event_uid (tenant_id, calendar_id, uid)`; index `ix_events_event_range (tenant_id, calendar_id, starts_at)` (the spec's index); index `ix_events_event_series (tenant_id, calendar_id, recurrence_until)` (the recurrence prefilter: `rrule IS NOT NULL AND (recurrence_until IS NULL OR recurrence_until >= :start)`); index `ix_events_event_publish_due (status, publish_at)` (PR 2's beat, read across tenants) |
  | `events_event_text` (`EventText`, audit) | `id` big PK; `event_id` UUID FK `events_event.id` cascade; `locale` str(16); `slug` str(200); `title` str(300); `summary` str(1000) nullable; `description` `Text`, default `""` (allow-listed HTML, written only by PR 2's sanitiser); `seo_title` str(300) nullable; `seo_description` str(500) nullable; `noindex` bool default False | unique `uq_events_event_text_locale (tenant_id, event_id, locale)`; unique `uq_events_event_text_slug (tenant_id, locale, slug)` |
  | `events_occurrence_override` (`OccurrenceOverride`, audit) | `id` big PK; `event_id` UUID FK cascade; `original_start` datetime; `kind` str(16); `starts_at`, `ends_at` datetime nullable (set only for `moved`); `note` str(1000) nullable | unique `uq_events_occurrence_override (tenant_id, event_id, original_start)` |
  | `events_revision` (`Revision`) | `id` big PK; `event_id` UUID FK cascade, indexed; `number` int; `action` str(24); `actor` str(255) nullable; `snapshot` JSON dict; `created_at` datetime (`dt_col(nullable=False)`) | unique `uq_events_revision_number (tenant_id, event_id, number)` |
  | `events_redirect` (`Redirect`) | `id` big PK; `locale` str(16); `old_slug` str(200); `event_id` UUID FK cascade, indexed; `created_at` datetime | unique `uq_events_redirect (tenant_id, locale, old_slug)` |

- [ ] **Step 1: Write the failing tests** in `tests/models/test_models.py`:
  - `test_every_table_is_tenant_owned`: `{t.name for t in Base.metadata.sorted_tables}` equals the seven names, and each has a `tenant_id` column.
  - `test_tenant_scoped_uniques_lead_with_tenant`: every unique constraint or unique index in `Base.metadata` has `tenant_id` as its first column.
  - `test_calendar_slug_unique_per_tenant`: two `Calendar(slug="team")` in `default` raise `IntegrityError` on flush. The same slug in tenant `b` (`unbound_tenant`, one `tenant_scope` each) is accepted.
  - `test_trashed_calendar_keeps_its_slug`: soft-delete one, then insert the same slug: `IntegrityError`.
  - `test_text_slug_unique_per_locale`: two texts `("en", "x")` fail; `("de", "x")` is accepted.
  - `test_foreign_keys`: in `Base.metadata`, `events_event.category_id`'s FK is `ondelete="SET NULL"`, and `calendar_id`, `parent_id` and every child table's `event_id` are `CASCADE`. Task 9's service nulls the category explicitly as well, because SQLite runs without FK enforcement.
  - `test_defaults`: a minimal `Event` flushes with `status == "draft"`, `revision == 1`, `type == "event"` and `extra == {}`.
  - `host/tests/test_events_wiring.py`: `EVENTS_TABLES` (the seven names); `test_host_metadata_has_events_tables` (`{t for t in build_module_metadata().tables if t.startswith("events_")} == EVENTS_TABLES`); `test_host_loads_the_module` (`"Events"` is in the module names).
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/models`, and from the root `uv run pytest -q host/tests/test_events_wiring.py`.
- [ ] **Step 3: Implement** the models.
- [ ] **Step 4: Generate the revision against a scratch SQLite database**, never `host/app.db`. First run `uv run python scripts/check_migration_heads.py`: it printed `One migration head: 541bfbe29a28` when this plan was written, and it changes if #405 has landed. With `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/events-mig.db` exported for each command, run `uv run --project host alembic -c host/alembic.ini upgrade heads`, then `make migration msg="add events"` (which is `alembic revision --autogenerate`). Open the file and set `branch_labels = ("events",)`. Check that `down_revision` is the head printed above, and that the revision creates exactly the seven `events_*` tables and their indexes and alters or drops nothing else. Delete any unrelated drift it picked up and report it in the summary rather than shipping it. Add a docstring saying what the revision creates and that PR 2 uses five of the tables, as the other revisions do. Then run `upgrade heads`, `alembic check` (expected: "No new upgrade operations detected"), `downgrade <the parent>`, `upgrade heads` and `check` again. Delete `/tmp/events-mig.db`.
- [ ] **Step 5: Postgres.** Use dev-services' Postgres (`make up` in dev-services if it is down; never a per-project container). Create a scratch `smpy_events_check` database, then with `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_events_check` run `upgrade heads`, `check`, `downgrade base`, `upgrade heads` and `check`. All pass. Drop the scratch database and say so in the summary.
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (expected: one head, the new revision), then the Step 2 tests (pass). Then create `smpy_events_test` and run `cd modules/events && SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_events_test uv run pytest -q tests/models` (passes on Postgres).
- [ ] **Step 7: Commit** `feat(events): every table of PRs 1 and 2 and their migration`.

### Task 6: The access policy and the `events.calendar` resource type

**Files:**
- Create: `sm_events/core/access/__init__.py` (the policy), `core/access/rights.py` (`CalendarRights`), `core/access/resource_types.py`
- Modify: `sm_events/module.py` (`register_resource_types`, `register_middleware`, as images' `module.py:82-97` does)
- Create: `tests/support/__init__.py`, `tests/support/access.py`
- Test: `tests/core/access/__init__.py`, `tests/core/access/test_policy.py`, `tests/core/access/test_resource_types.py`

**Interfaces:**

```python
# core/access/__init__.py (modelled on modules/images/sm_images/core/access/__init__.py:58-155)
CALENDAR_RESOURCE = "events.calendar"
ACTION_WRITE_EVENTS = "write_events"     # module-internal action; PR 2's event writes
class CalendarPolicy:                     # the framework's ResourcePolicy protocol
    def predicate(self, who: ResourcePrincipal, action: str) -> ColumnElement | None
    def filter(self, who, action, stmt) -> Select
    def can(self, who, action, obj: Calendar) -> bool
POLICY: CalendarPolicy
def visible_calendars(who, action: str = ACTION_VIEW) -> Select   # trash excluded by the mixin
def calendar_stmt(calendar_id: uuid.UUID) -> Select
CalendarView  = Annotated[Calendar, Depends(_Requires(ACTION_VIEW))]
CalendarEdit  = Annotated[Calendar, Depends(_Requires(ACTION_EDIT))]
CalendarOwner = Annotated[Calendar, Depends(_Requires(ACTION_DELETE, owner=True))]
    # _Requires wraps RequiresResource and translates its 403/404 into events errors.

# core/access/rights.py
@dataclass(frozen=True)
class CalendarRights:
    view: bool; edit_calendar: bool; own: bool; write_events: bool; see_drafts: bool; publish: bool
async def calendar_rights(db, who: ResourcePrincipal, calendar: Calendar) -> CalendarRights
    # one SELECT per action through POLICY.filter (a share is a row: can() cannot see it);
    # see_drafts == write_events; publish == write_events and who.has(PERM_PUBLISH)

# core/access/resource_types.py: images' resource_types.py:46-66 with Calendar and sm_events names
def calendar_loader() -> Callable[[str], Select]
def register(registry: ResourceTypeRegistry) -> None
```

- Constants: `OWNER_ONLY_DETAIL = "Only the calendar's owner or an events manager can do this"`.
- **How `predicate` is built.** `M` means `who.has(PERM_MANAGE)`, `V` means `who.has(PERM_VIEW)`, `signed` means `who.user_id is not None`. `share(a)` is `share_exists_for(CALENDAR_RESOURCE, Calendar.id)(who, a)`, restricted to `view`/`edit`. For `write_events`, call it with `edit`. `owner` is `Calendar.owner_id == who.user_id`.
  - `M` gives `None` for every action (bypass).
  - `not V` or `not signed`: `view` gives `visibility == public`; every other action gives `false()`.
  - `view` gives `owner OR share(view) OR visibility IN (internal, public)`.
  - `edit` gives `owner OR share(edit)`.
  - `delete` and `share` give `owner`.
  - `write_events` gives `owner OR share(edit) OR (has(PERM_EDIT) AND visibility IN (internal, public))`.
  - Any other action gives `false()`.

  `can()` mirrors `predicate` in Python, except that a share always answers `False` (`load_authorized` then re-asks through `filter`, as `simple_module_db/resource_policy.py:129-149` does). The sharing service checks the granter with `ACTION_SHARE` (`sharing/core/service.py:81`), so `share` must be owner or `M` only.
- `register_middleware(app)`: `app.add_middleware(RequestContextMiddleware)`. `register_resource_types(registry)`: `resource_types.register(registry)`.

- [ ] **Step 1: Write the failing tests.** `tests/support/access.py` provides `principal(user_id: str | None, *perms: str) -> ResourcePrincipal` and `async seed_calendars(db) -> dict[str, Calendar]`. The latter seeds three calendars, `P` (private), `I` (internal) and `U` (public), all owned by `"o"`. It grants user `"sv"` a view share and user `"se"` an edit share on all three, through `sharing.models.ResourceShare` rows with the tenant pinned. `test_policy.py::test_truth_table` is parametrized over the table below. For each `(principal, action)`, it asserts that the set of calendar letters returned by `db.execute(POLICY.filter(who, action, select(Calendar)))` equals the expected set, and that `calendar_rights` agrees with it for every calendar.

  | principal | perms | view | edit | delete / share | write_events | publish |
  |---|---|---|---|---|---|---|
  | `M` (`"m"`) | manage | PIU | PIU | PIU | PIU | ∅ (no `events.publish`) |
  | `M+P` (`"m"`) | manage, publish | PIU | PIU | PIU | PIU | PIU |
  | `O` (`"o"`) | view | PIU | PIU | PIU | PIU | ∅ |
  | `O+P` (`"o"`) | view, publish | PIU | PIU | PIU | PIU | PIU |
  | `O-` (`"o"`) | (none) | U | ∅ | ∅ | ∅ | ∅ |
  | `SV` (`"sv"`) | view, edit | PIU | ∅ | ∅ | IU | ∅ |
  | `SV-` (`"sv"`) | (none) | U | ∅ | ∅ | ∅ | ∅ |
  | `SE` (`"se"`) | view | PIU | PIU | ∅ | PIU | ∅ |
  | `E` (`"e"`) | view, edit | IU | ∅ | ∅ | IU | ∅ |
  | `E+P` (`"e"`) | view, edit, publish | IU | ∅ | ∅ | IU | IU |
  | `V` (`"v"`) | view | IU | ∅ | ∅ | ∅ | ∅ |
  | `N` (`"n"`) | (none) | U | ∅ | ∅ | ∅ | ∅ |
  | `A` (anonymous) | (none) | U | ∅ | ∅ | ∅ | ∅ |

  Also write:
  - `test_expired_share_grants_nothing`: an `SE` share with `expires_at` in the past gives `SE` only `IU` on view and nothing on edit.
  - `test_share_never_grants_delete`: `POLICY.can(SE, "delete", P)` is False, and so is `filter`.
  - `test_trashed_calendar_invisible`: a soft-deleted `I` disappears for `V` and for `M`.
  - `test_resource_types.py::test_registered`: `ResourceTypeRegistry` holds `events.calendar` with `POLICY`.
  - `test_loader_uses_bound_tenant`: under `tenant_scope("default")`, `calendar_loader()(str(id))` selects the row.
  - `test_loader_single_host_without_binding` (`unbound_tenant`): with a fake current request in SINGLE mode, the statement is pinned to `default` and finds the calendar; a calendar of tenant `b` is not found.
  - `test_loader_multi_without_tenant_raises` (`unbound_tenant`): MULTI mode with nothing resolved raises `TenantRequired`.
  - `test_loader_no_request_raises`.
  - `test_loader_bad_id_is_value_error`.

  Port the last five from images' `tests/core/access/test_resource_types.py` (`ls modules/images/tests/core/access`).
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/core/access`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and on Postgres (`SM_TEST_DATABASE_URL`). Both pass.
- [ ] **Step 5: Commit** `feat(events): calendar access policy and the events.calendar resource type`.

### Task 7: Calendar service and API

**Files:**
- Create: `sm_events/calendar/__init__.py` (docstring), `calendar/slugs.py`, `calendar/calendars.py`
- Create: `sm_events/web/__init__.py`, `web/endpoints/__init__.py` (`build_api_router()`, as in `modules/newsletter/sm_newsletter/web/endpoints/__init__.py`), `web/endpoints/deps.py`, `web/endpoints/calendars_api.py`, `web/schemas/__init__.py`, `web/schemas/calendars.py`
- Modify: `sm_events/module.py` (`register_routes`: the API router wrapped in `Depends(RequiresCsrf())`, as newsletter's `module.py:91-99` does)
- Create: `tests/support/app.py` (a FastAPI app with `EventsModule` registered on a test `db_state`, sharing's module and tables, and a header-driven fake principal; copy the shape of images' `tests/support/app_harness.py`)
- Test: `tests/calendar/__init__.py`, `tests/calendar/test_slugs.py`, `tests/calendar/test_calendars.py`, `tests/web/__init__.py`, `tests/web/test_calendars_api.py`

**Interfaces:**

```python
# calendar/slugs.py
def slugify(text: str) -> str          # NFKD, ascii, lower, non [a-z0-9] runs -> "-", trimmed, <= SLUG_MAX; "" -> SLUG_FALLBACK
async def free_slug(db, model: type, base: str) -> str   # "-2", "-3", ... while taken (trash included)

# calendar/calendars.py  (no commit; the endpoint finishes with simple_module_db.finalize_session)
async def list_calendars(db, who, *, trashed: bool = False) -> list[Calendar]
    # visible_calendars(who); trashed=True lists only trashed rows who may `delete`
    # (include_deleted=True + POLICY.filter(who, "delete", ...)); ordered by name; at most CALENDARS_MAX
async def create_calendar(db, who, data: CalendarCreate, *, default_tz: str) -> Calendar
    # owner_id = who.user_id; slug = data.slug (SlugTaken if taken) or free_slug(slugify(name));
    # default_timezone = data.default_timezone or timezones.effective(default_tz);
    # IntegrityError on the slug index -> SlugTaken
async def update_calendar(db, cal: Calendar, data: CalendarPatch) -> Calendar   # only fields set
async def set_visibility(db, cal: Calendar, visibility: Visibility) -> Calendar
async def trash_calendar(db, cal: Calendar) -> None                            # soft delete
async def restore_calendar(db, who, calendar_id: uuid.UUID) -> Calendar
    # loads with include_deleted through POLICY.filter(who, "delete"); NotFound when absent
    # or not deleted; a trashed row is invisible to non-owners, so refusal is always NotFound
```

- Constants: `CALENDARS_MAX = 500`, `SLUG_FALLBACK = "calendar"`, `SLUG_TAKEN_DETAIL = "That slug is already in use"`.
- Schemas (`web/schemas/calendars.py`):
  - `CalendarCreate`: `name` (1-200, stripped), `slug: str | None` (matches `SLUG_PATTERN`, ≤80), `color` (`COLOR_PATTERN`, lower-cased; default `DEFAULT_COLOR`), `description: str | None` (≤2000), `visibility: Visibility = PRIVATE`, `default_timezone: str | None` (`timezones.is_known` or a validation error).
  - `CalendarPatch`: metadata fields are optional; `visibility` is excluded and only `PUT …/visibility` sets it.
  - `VisibilityIn {visibility: Visibility}`.
  - `CalendarOut`: `id`, `slug`, `name`, `color`, `description`, `visibility`, `owner_id`, `default_timezone`, `sources`, `created_at`, `updated_at`, `deleted_at`, plus `can_edit`, `can_own`, `can_write_events` and `can_publish` from `calendar_rights`.
- Routes. The parent API router binds `bind_admin`; the calendars router is `APIRouter(prefix="/calendars", dependencies=[require_view])`, so every route requires `events.view`:

  | Method and path | Extra guard | Success | Errors |
  |---|---|---|---|
  | `GET /api/events/calendars?trashed=false` | none | 200 `list[CalendarOut]` | none |
  | `POST /api/events/calendars` | `events.edit` | 201 | 409 `slug_taken`; 422 |
  | `GET /api/events/calendars/{id}` | `CalendarView` | 200 | 404 `not_found` |
  | `PATCH /api/events/calendars/{id}` | `CalendarEdit` | 200 | 404 (invisible), 403 `forbidden` (visible, not editable), 409 `slug_taken`, 422 |
  | `PUT /api/events/calendars/{id}/visibility` | `CalendarOwner` | 200 | 404, 403 `owner_required` |
  | `PUT /api/events/calendars/{id}/owner` | `events.manage` and `CalendarOwner`; active tenant member | 200 | 404, 422 `owner_not_allowed`, 503 `user_directory_unavailable` |
  | `DELETE /api/events/calendars/{id}` | `CalendarOwner` | 204 | 404, 403 `owner_required` |
  | `POST /api/events/calendars/{id}/restore` | owner or `events.manage` (service) | 200 | 404 `not_found` |

  `_Requires` translates `RequiresResource`'s `PermissionDenied` and 404 into `Forbidden`/`OwnerRequired` and `NotFound`, using `{"detail","code"}`. The framework's router permission gates keep their own error shape. PR 1 has a Trash tab with restore, but no hard delete (purge).

- [ ] **Step 1: Write the failing tests.**
  - `test_slugs.py`: `slugify("Team Ärger 2026!") == "team-arger-2026"`, `slugify("!!!") == "calendar"`, and an 81-character name is cut to ≤80 with no trailing `-`.
  - `test_calendars.py`:
    - `test_create_owner_and_defaults`: the caller owns the calendar; visibility is `private`, colour `#2563eb`, timezone the setting's.
    - `test_slug_derived_and_deduplicated`: two "Team" calendars get `team` and `team-2`.
    - `test_slug_held_by_trashed_calendar_is_taken`: `SlugTaken`.
    - `test_slug_race_is_conflict`: monkeypatch the pre-check to report free; the `IntegrityError` becomes `SlugTaken`.
    - `test_restore_round_trip`.
    - `test_list_trashed_only_own_or_manage`.
  - `test_calendars_api.py` (through `tests/support/app.py`):
    - `test_create_needs_events_edit`: `V` gets 403, `E` gets 201.
    - `test_bad_timezone_and_color_are_422`.
    - `test_stranger_sees_404_everywhere`: `V` on `P` gets 404 for GET, PATCH, PUT visibility, DELETE and restore.
    - `test_share_holder_403s`: `SV` PATCH gets 403 `forbidden`; `SE` PATCH gets 200; `SE` PUT visibility and DELETE get 403 `owner_required`.
    - `test_manage_bypasses`: `M` can do everything on someone else's private calendar.
    - `test_error_envelope`: every non-422 error body has exactly the keys `detail` and `code`.
    - `test_rights_in_out`: `can_publish` is false for `O` and true for `O+P`.
    - `test_tenant_isolation` (`unbound_tenant`, multi mode through the request's `tenant_id`): a calendar of tenant `a` is a 404 from tenant `b`.
    - `test_multi_without_tenant_is_403_tenant_required`.
    - `test_writes_need_csrf`: a POST without the token gets 403 from `RequiresCsrf`.
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/calendar tests/web/test_calendars_api.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and Postgres (both pass), then the fresh-import check: `uv run python -c "import sm_events.web.endpoints.calendars_api, sm_events.calendar.calendars, sm_events.core.access.resource_types, sm_events.module"` exits 0.
- [ ] **Step 5: Commit** `feat(events): calendars API with visibility, trash and restore`.

### Task 8: Share candidates and sharing end to end

**Files:**
- Create: `sm_events/web/endpoints/shares_api.py` (a copy of `modules/images/sm_images/web/endpoints/api/shares.py:135-196` with `CalendarOwner`, the events names and `PATH_PATTERN = rf"^{ROUTE_PREFIX_API}/calendars/[^/]+/share-candidates$"`), `web/schemas/shares.py` (`ShareCandidate {id, display_name, email}`)
- Modify: `web/endpoints/__init__.py` (include it), `sm_events/module.py` (`register_rate_limits`: `registry.add_regex(shares_api.PATH_PATTERN, RateLimitRule(shares_api.RATE, key="user", methods=frozenset({"GET"})))`, as images' `module.py:129-140` does), `core/constants.py` (`CANDIDATES_MAX = 20`, `CANDIDATES_SCAN = 100`, `DIRECTORY_UNAVAILABLE_CODE = "user_directory_unavailable"`, `DIRECTORY_UNAVAILABLE_DETAIL`)
- Test: `tests/web/test_shares_api.py`

**Interfaces:**
- `GET /api/events/calendars/{id}/share-candidates?q=` (≤100 characters). Needs `events.view` and `CalendarOwner`. Answers `list[ShareCandidate]` (at most 20, the owner excluded, active users only). With a directory installed, `q` shorter than `MIN_QUERY = 3` once trimmed gives `[]` without searching it. Unless the host is single-tenant with nothing upstream (`unscoped_single`), only members of the bound tenant are offered (`tenant_member_ids`, fail closed). `NullUserDirectory` gives 503 `user_directory_unavailable`, including for a short query.
- Scan at most 100 directory matches, then match display-name text with address tokens removed or an exact full address. Mask email and address-bearing labels unless the trimmed query equals the full address (case-insensitive); apply these filters before the 20-candidate limit.
- Grants, lists and revokes go through the framework's `/api/sharing/shares` with `resource_type="events.calendar"` and `resource_id=str(calendar.id)`. Events adds no share routes of its own.

- [ ] **Step 1: Write the failing tests** (a fake `UserDirectory` installed on the test app, as images' `tests/web/…/test_shares*.py` does):
  - `test_owner_gets_candidates`.
  - `test_short_query_is_empty_without_directory_call`.
  - `test_edit_share_holder_is_403`.
  - `test_stranger_is_404`.
  - `test_other_tenant_members_not_offered` (multi mode, a membership stub).
  - `test_no_directory_is_503`.
  - `test_grant_through_sharing_api_single_host`: the owner `POST`s `/api/sharing/shares` for `events.calendar` on a single-tenant app with nothing bound; the grantee (with `events.view`) then sees `P` in `GET /api/events/calendars`.
  - `test_edit_share_holder_cannot_grant`: `SE` posting a share gets 403/404 from sharing.
  - `test_share_list_needs_events_view`: `SV-` asking `GET /api/sharing/shares?resource_type=events.calendar&resource_id=<P>` is refused (404).
  - `test_rate_limit_rule_registered`: `PATH_PATTERN` is in the app's rate-limit registry with `"60/minute"`.
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/web/test_shares_api.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same: passes.
- [ ] **Step 5: Commit** `feat(events): calendar share picker and sharing wiring`.

### Task 9: Categories service and API

**Files:**
- Create: `sm_events/calendar/categories.py`, `web/endpoints/categories_api.py`, `web/schemas/categories.py`
- Modify: `web/endpoints/__init__.py`
- Test: `tests/calendar/test_categories.py`, `tests/web/test_categories_api.py`

**Interfaces:**

```python
async def list_categories(db) -> list[Category]                       # ordered by slug
async def create_category(db, data: CategoryCreate, *, locales: tuple[str, ...]) -> Category
async def update_category(db, cat: Category, data: CategoryPatch, *, locales) -> Category
async def delete_category(db, cat: Category) -> None
    # UPDATE events_event SET category_id = NULL WHERE tenant_id = :t AND category_id = :id
    # (explicit: SQLite runs without FK enforcement), then DELETE the row
```

- `CategoryCreate`: `slug: str | None` (pattern; derived from the default locale's name when absent, through `free_slug`), `names: dict[str, str]` (non-empty; each name 1-100 characters; one for `content_locales[0]` is required), `color: str | None` (`COLOR_PATTERN`). A key outside `content_locales` raises `UnknownLocale` (422 `unknown_locale`), checked in the service against `request.app.state.sm_events.settings.content_locales`. `CategoryOut`: `id`, `slug`, `names`, `color`.
- Routes under `bind_admin`, all requiring `events.view`: `GET /api/events/categories` (up to 500 rows); `POST` (also `events.manage`, 201, 409 `slug_taken`, 422); `PATCH /{id}` and `DELETE /{id}` (also `events.manage`; 404 `not_found` for an unknown id or one from another tenant; DELETE answers 204).

- [ ] **Step 1: Write the failing tests:**
  - `test_create_derives_slug_from_default_locale_name`.
  - `test_unknown_locale_is_422` (with `content_locales=("en","de")`, `{"fr": …}` fails).
  - `test_default_locale_name_required`.
  - `test_delete_nulls_events_category` (insert an `Event` row directly).
  - `test_view_can_list_manage_writes`: `V` gets 200 on GET and 403 on POST; `M` gets 201.
  - `test_slug_taken_409`.
  - `test_tenant_isolation` (`unbound_tenant`).
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/calendar/test_categories.py tests/web/test_categories_api.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): categories API`.

### Task 10: Views, menu and host wiring tests

**Files:**
- Create: `sm_events/web/endpoints/views.py`, `web/endpoints/menu.py`
- Modify: `sm_events/module.py` (`register_routes` includes `views.router` on the view router; `register_menu_items`), `core/constants.py`, `locales/en.json` and `de.json` (`menu.*`)
- Modify: `host/tests/test_events_wiring.py` (views and menu), `host/tests/test_menu_labels.py` (add `"sm_events"` to `_OUR_PACKAGES`, lines 20-28; `"events."` to `_OUR_NAMESPACES`, line 29; the item count at line 70 goes from 14 to 16), `host/tests/test_host_boots.py` (add `"Events"` to `REPO_MODULES`, line 94. Events subscribes to no records event, so the `{"SubscriptionChanged"}` assertion at line 159 stays true and gains evidence)
- Test: `tests/web/test_views.py`

**Interfaces:**
- Constants: `_PAGE_CALENDARS = f"{MODULE_NAME}/Calendars"`, `_PAGE_CATEGORIES = f"{MODULE_NAME}/Categories"`, `CALENDARS_URL = f"{VIEW_PREFIX}/calendars"`, `CATEGORIES_URL = f"{VIEW_PREFIX}/categories"`, `MENU_GROUP = "Events"`, `MENU_GROUP_KEY = "events.menu.group"`, `MENU_LABEL_CALENDARS = "Calendars"`, `MENU_LABEL_KEY_CALENDARS = "events.menu.calendars"`, `MENU_ICON_CALENDARS = "calendar"`, `MENU_LABEL_CATEGORIES = "Categories"`, `MENU_LABEL_KEY_CATEGORIES = "events.menu.categories"`, `MENU_ICON_CATEGORIES = "tag"`.
- `views.router = APIRouter(dependencies=[Depends(bind_admin)])`, modelled on `modules/newsletter/sm_newsletter/web/endpoints/views.py:25-49`:
  - `GET /` (`events.view`) gives `RedirectResponse(CALENDARS_URL, 303)`.
  - `GET /calendars` (`events.view`) renders `_PAGE_CALENDARS` with `{**tenancy.view_props(request), "can_create": grants(held, PERM_EDIT), "can_manage": grants(held, PERM_MANAGE), "default_timezone": timezones.effective(settings.default_timezone), "user_id": <current user id>}`.
  - `GET /categories` (`events.view` and `events.manage`) renders `_PAGE_CATEGORIES` with `{**view_props, "content_locales": list(settings.content_locales)}`.
- `menu_items()`: Calendars (`order=400`, `permissions=[PERM_VIEW]`) and Categories (`order=410`, `permissions=[PERM_VIEW, PERM_MANAGE]`), both in group `MENU_GROUP`/`MENU_GROUP_KEY`.

- [ ] **Step 1: Write the failing tests:**
  - `test_views.py::test_root_redirects_to_calendars`.
  - `test_calendars_page_props` (send `X-Inertia: true` and `X-Inertia-Version`; the component is `Events/Calendars` and the flags match the principal).
  - `test_categories_page_needs_manage` (403 for `V`).
  - `test_events_wiring.py::test_views_and_menu_mounted`: the paths include `{"/admin/events/", "/admin/events/calendars", "/admin/events/categories"}`, and the menu URLs in group `Events` are `{CALENDARS_URL, CATEGORIES_URL}`.
  - `test_resource_type_and_middleware`: `app.state.sm.resource_types.get("events.calendar")` is not None, and `RequestContextMiddleware` is in `app.user_middleware`.
  - The `test_menu_labels.py` and `test_host_boots.py` edits above.
- [ ] **Step 2: Run them to see them fail.** `cd modules/events && uv run pytest -q tests/web/test_views.py`, then from the root `uv run pytest -q host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same: passes. Also run `uv run python scripts/check_hardcoded_strings.py` and `scripts/check_locales.py`.
- [ ] **Step 5: Commit** `feat(events): console views and menu`.

### Task 11: The Calendars screen with the share dialog

**Files:**
- Create: `sm_events/pages/Calendars.tsx`
- Create: `sm_events/ui/utils/api.ts`, `ui/utils/api-shares.ts`, `ui/utils/types.ts`
- Create: `sm_events/ui/hooks/useCalendars.ts`, `ui/hooks/useShares.ts`
- Create: `sm_events/ui/components/calendars/CalendarDialog.tsx`, `ui/components/calendars/CalendarRow.tsx`, `ui/components/calendars/VisibilityMenu.tsx`, `ui/components/share/ShareDialog.tsx`, `ui/components/ConfirmDialog.tsx`
- Create: `sm_events/ui/page-tests/support.tsx`, `ui/page-tests/test-dom.tsx` (copies of images'), `ui/page-tests/Calendars.test.tsx`, `ui/page-tests/ShareDialog.test.tsx`
- Modify: `locales/en.json` and `de.json` (`calendars.*`, `share.*`, `visibility.*`, `errors.*`)

**Interfaces:**
- `ui/utils/api.ts`: a client over `apiFetch` from `@simple-module-py/ui/lib/api` (billing's precedent, `modules/billing/sm_billing/ui/utils/api.ts:3`). `ApiError {status, code}`, and `errorText(err): string` maps `slug_taken`, `owner_required`, `forbidden`, `not_found`, `tenant_required` and `user_directory_unavailable` to `keys.events.errors.*`. It exports `listCalendars(trashed?)`, `createCalendar(body)`, `updateCalendar(id, body)`, `setVisibility(id, v)`, `trashCalendar(id)` and `restoreCalendar(id)`.
- `ui/utils/api-shares.ts`: images' `modules/images/sm_images/ui/utils/api-shares.ts` with `RESOURCE_TYPE = 'events.calendar'` and the candidates URL `/api/events/calendars/{id}/share-candidates`. `useShares.ts` and `ShareDialog.tsx` are images' (`ui/hooks/useShares.ts`, `ui/components/share/ShareDialog.tsx`) moved onto events' keys and `api` helpers. The test ids are `events-share` and `events-share-search`.
- `pages/Calendars.tsx` (`export default`) takes the props from Task 10. It shows a table with a colour swatch, name, slug, a visibility badge, the timezone and, when `owner_id !== user_id`, the owner. Each row offers Edit when `can_edit`, and Visibility, Share and Move to trash when `can_own`. The page has a "New calendar" button when `can_create`, and an Active/Trash toggle where the Trash rows offer Restore. `CalendarDialog` handles create and edit: name, an optional slug, a colour (`<input type="color">`), a description, and a timezone field backed by a `datalist` from `Intl.supportedValuesOf('timeZone')`, which the server validates again. A visibility select appears only on create.

- [ ] **Step 1: Write the failing tests** (happy-dom, `stubFetch` as in `modules/images/sm_images/ui/page-tests/ShareDialog.test.tsx:1-40`):
  - `Calendars.test.tsx`:
    - `lists calendars with visibility badges`.
    - `hides New calendar without can_create`.
    - `creates a calendar and shows it` (asserts the POST body and the CSRF header present).
    - `shows the slug_taken message on 409`.
    - `offers Share, Visibility and Trash only when can_own`.
    - `trash then restore`.
  - `ShareDialog.test.tsx`: a port of images' cases with the events resource type and URLs: lists current shares, searches after 3 characters, grants view and edit, revokes.
- [ ] **Step 2: Run them to see them fail.** `~/.claude/bin/wait-for-headroom`, then `npx vitest run modules/events`.
- [ ] **Step 3: Implement.** Every string goes through `t(keys.events.…)`. Add each key to `en.json` and `de.json` together.
- [ ] **Step 4: Run** `npx vitest run modules/events`, `npx tsc --noEmit -p modules/events/tsconfig.json`, `npx biome check modules/events`, `uv run python scripts/check_rules.py` (pages) and `scripts/check_ts_imports.py`. All pass.
- [ ] **Step 5: Commit** `feat(events): Calendars screen with sharing`.

### Task 12: The Categories screen

**Files:**
- Create: `sm_events/pages/Categories.tsx`, `ui/components/categories/CategoryDialog.tsx`, `ui/hooks/useCategories.ts`, `ui/page-tests/Categories.test.tsx`
- Modify: `ui/utils/api.ts` (`listCategories`, `createCategory`, `updateCategory`, `deleteCategory`), `ui/utils/types.ts`, `locales/en.json`, `locales/de.json` (`categories.*`)

**Interfaces:**
- `pages/Categories.tsx` (props `{content_locales: string[]}`): a table of colour, slug and the name in each locale, with Edit and Delete (behind `ConfirmDialog`, saying that events keep running uncategorised). `CategoryDialog` shows one name input per content locale (the first required), an optional slug and a colour.

- [ ] **Step 1: Write the failing tests:** `renders one name field per content locale`, `creates with names keyed by locale`, `shows unknown_locale and slug_taken messages`, `delete asks first`.
- [ ] **Step 2: Run them to see them fail.** `npx vitest run modules/events/sm_events/ui/page-tests/Categories.test.tsx`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the vitest, tsc and biome commands from Task 11: all pass.
- [ ] **Step 5: Commit** `feat(events): Categories screen`.

### Task 13: Docs, repo prose and branch verification

**Files:**
- Modify: `modules/events/README.md`. Finish it: what the module does, Install (dependency, `make install`, migration with the `events` branch label), Usage (the screens, the API table from Task 7, sharing through the framework's sharing API), Settings (the two fields; DB-backed, no env), Permissions and the access rules in prose, and Status (PR 1 of 10, link to the spec).
- Modify: `modules/events/docs/index.md`. Add an "Access" section with the truth table from Task 6 in prose and table form, a "Tenancy" section (the copy, `bind_admin`, the sharing loader's rule), "Data model" (the seven tables, which PR uses each) and "Status".
- Modify: `README.md` (module table, lines 13-21). Add the row ``| `modules/events` | [`simple_module_events`](https://pypi.org/project/simple_module_events/) | Calendars and events — shareable private, internal or public calendars; recurring events, public pages and ICS feeds arrive in the next releases |``.
- Modify: `docs/module-layout.md` ("Where each module stands"). Add an `events` row with counts from `ls` (root `.py` files, root folders, `0` flat test files, "follows this layout"), and newsletter's missing row too.
- Modify: `CHANGELOG.md`. Under `## 0.0.16 (unreleased)` (line 6), add an `### Added` section: "**events: a new module** (`simple_module_events`, #400): calendars with private, internal and public visibility, shared through the sharing module, the Calendars and Categories screens and their API. Hosts add the dependency and run the `events` migration."
- Modify: `CLAUDE.md`, minimally:
  - line 115: "…images, newsletter and events entry point…";
  - line 118: "all five" becomes "all six";
  - line 135: "…and events' `sm_events.core.tenancy` is a copy of newsletter's";
  - line 272: add `events` to the "read no environment variables" list;
  - line 507: correct "All seven ship" to the real module count.
- Modify: `docs/superpowers/specs/2026-11-17-events-module-design.md`. Add a short "Amendments (PR 1)" section listing the rulings above that refine the spec: the create permission, the `events.view` rule, `VARCHAR` visibility, no `expected_revision` on calendars, and categories moved into PR 1.

- [ ] **Step 1: Lint set.** Run `~/.claude/bin/wait-for-headroom`, then from the root:
  - `uv run ruff check modules/events scripts host`
  - `uv run ruff format --check modules/events host/tests/test_events_wiring.py`
  - `uv run basedpyright` (expected unchanged: events adds nothing to `include`)
  - `npx biome check modules/events`
  - `npx tsc --noEmit -p modules/events/tsconfig.json`
  - `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py`, `check_locales.py`, `check_migration_heads.py` and `bump_version.py --check-current`

  All must pass. A WARNING at 280+ lines means splitting that file now.
- [ ] **Step 2: Targeted suites, one at a time.**
  1. `cd modules/events && uv run pytest -q -n 8` on SQLite.
  2. The same with `SM_TEST_DATABASE_URL` set to `smpy_events_test` on dev-services' Postgres.
  3. From the root: `uv run pytest -q -n 8 scripts/tests host/tests/test_tenancy_parity.py host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`.
  4. `npx vitest run modules/events`.

  All pass. Do **not** run the other modules' suites or `make test-py`; `/ship` does.
- [ ] **Step 3: Fresh-import check.** For every module under `sm_events`, `uv run python -c "import <module>"` exits 0. Loop over `find modules/events/sm_events -name '*.py'` from the root.
- [ ] **Step 4: Commit** `docs(events): README, module docs, changelog and repo prose`.
- [ ] **Step 5: Hand over to `/ship`.** It runs the full suites once, then QA in the browser: create a calendar, edit it, change its visibility, share it with a second user who then sees it, trash and restore it, and create a category in English and German. Screenshots of the Calendars screen, the share dialog and the Categories screen go in the PR.

## Verification checklist (before `/ship`)

- `make lint` pieces from Task 13 Step 1 all pass.
- Events pytest passes on SQLite and Postgres. `scripts/tests` and the four host tests pass.
- `npx vitest run modules/events` passes.
- `alembic check` reports "No new upgrade operations detected" on SQLite and Postgres after `upgrade heads`, a downgrade and another upgrade. `check_migration_heads.py` reports one head, the new revision, labelled `events`.
- The fresh-import check passes for every module.
- No file under `modules/events` reaches 280 lines.
- `git diff --stat origin/main` touches only `modules/events/**`, `host/pyproject.toml`, `host/migrations/versions/<rev>_add_events.py`, the four host tests, `scripts/tests/parity_*.py`, the root `pyproject.toml`, `uv.lock`, `package-lock.json`, `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.

## Remaining follow-ups

The creation, event-writing, slug-rename and ownership-transfer decisions are resolved in "Rulings on the open points" above. A calendar retains its `owner_id` if that account is deleted or leaves; visibility and shares still apply, and a manager can transfer it to an active tenant member.

- Newsletter remains absent from the host tests' `REPO_MODULES` and `_OUR_PACKAGES`; that omission predates this PR.
- Re-check framework floors when imports move (`host/tests/test_host_boots.py` fails on a deprecated path).
- Images and events each have a `ShareDialog`, with no TS parity check. A shared sharing UI is an upstream follow-up.
