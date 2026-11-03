# Newsletter PR 2 — module scaffold, schema and suppression mirror — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `modules/newsletter` (`simple_module_newsletter`, package `sm_newsletter`) wired into the workspace and host, with every table the roadmap needs in one migration, DB-backed settings, tenancy, permissions, and an unsubscribe-suppression mirror (event handler plus hourly reconcile) fed by records' newsletter contract.

**Architecture:** A module laid out per `docs/module-layout.md` with images as the reference: `core/` holds constants, errors, settings, crypto, tenancy (a copy of images' copy of records'), clock, the worker DB runtime and `suppression/`; `models/` holds all nine tables. Records owns subscribers. Newsletter reads them only through `sm_records.contracts.newsletter` and keeps its own `newsletter_suppression` rows, keyed by an email hash. A volatile `SubscriptionChanged` handler and an hourly Celery beat task keep those rows in step. No routes, pages or menu yet.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async, Alembic, Celery via `simple_module_background_tasks`, `cryptography` (Fernet), pytest (SQLite; Postgres opt-in via `tests/pg_support.py`), TypeScript (`tsc`, vitest) for the i18n surface only.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md` (its "Amendments" section overrides earlier text). Roadmap: `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`. PR 1 contracts: `modules/records/sm_records/contracts/newsletter.py`, `modules/news/news/contracts/articles.py`.

## Rulings

- **Ruling: all nine tables ship now in one revision** (`newsletter_list`, `_campaign`, `_segment`, `_send`, `_send_attempt`, `_link`, `_click`, `_suppression`, `_dispatch_lock`), so PRs 3–7 add behaviour and no migration. If a later PR needs a column, it adds a normal revision. That is allowed, but avoiding it is the aim.
- **Ruling: statuses, reasons and kinds are `VARCHAR` with Python constants, never a Postgres enum.** Adding a value later (an `outcome_unknown` error kind, a new send status) then needs no migration and no enum-type drop on downgrade. Values are validated in code.
- **Ruling: add a `newsletter_list` registry table** `(tenant_id, type_key, created_at, last_reconciled_at)`, which the spec does not have. The reconcile needs to know which `(tenant, list)` pairs to walk. Records has no "list my subscription types" contract, and newsletter must not read records' tables. The mirror registers a list on any `SubscriptionChanged` for it. Later PRs register a list when it is created or first used by a campaign (`register_list`). A records list that exists before newsletter is installed is mirrored from its first event or registration (documented gap).
- **Ruling: suppressions are scoped.** An `unsubscribed` row carries the list's `type_key` in `list_type_key`. `hard_bounce`, `complaint` and `imported_cleaned` rows are address-wide (`list_type_key = ""`, never `NULL`, so the unique index works on both backends). A recipient is suppressed for list L if any row has `list_type_key in ("", L)`. A confirmation on L deletes L's `unsubscribed` row and the address-wide `hard_bounce` and `imported_cleaned` rows. It **never** deletes `complaint`, and never deletes another list's `unsubscribed` row.
- **Ruling: `email_hash = sha256(email.strip().lower()).hexdigest()`**, unkeyed. The normalisation is records' own (`subscribe.py`, `submit.py`: `strip().lower()`, no NFC and no Gmail dot folding), so both sides agree on what "the same address" is. There is no HMAC for three reasons. A rotated `SM_SECRET_KEY` would orphan every suppression, which is anti-goal 1. The reconcile worker and the import must hash with no secret. And the hash is not a privacy control: records stores the address in plain text. What the hash does is keep proof of an opt-out after records purges the address. Accepted: a known address can be confirmed by brute force.
- **Ruling: the mirror acts on the subscriber's *current* status, not the event's.** On `SubscriptionChanged` the handler reads the subscriber with `subscribers_by_uuid` (the event carries no address, amendment 1) and does nothing unless `hit.status == event.status_after`. A late "unsubscribed" event for someone who has since reconfirmed must not suppress them, and the confirm event handles them. An `unsubscribed` subscriber who is trashed is still mirrored. A trashed subscriber who is `confirmed` clears nothing. A purged record (no hit) does nothing: that is the gap amendment 1 accepts.
- **Ruling: the hourly reconcile ships in this PR**, not in PR 4 as the roadmap table says. It is the same mirror, and amendment 1 makes the handler untrusted on its own. The roadmap row for PR 4 is edited to match (Task 9). The reconcile only **adds** rows. It never clears, so a lost confirm event leaves the address suppressed, which fails safe. PR 6's admin lift handles that case.
- **Ruling: `smtp_password` is stored as `enc:v1:<fernet>` under `SM_SECRET_KEY`.** `sm_newsletter/core/crypto.py` is a copy of `sm_ai/core/crypto.py`, pinned by a parity family. A plain-text value written through the generic Settings screen or `set_setting.py` is accepted with a one-time warning, as ai does. PR 2 has no settings page, so no `manage_url` is set. PR 3, whose test send first uses the password, adds the newsletter settings page that encrypts on save and sets `manage_url` then.
- **Ruling: no `contracts/`, routes, pages, menu entry or Inertia dependency in PR 2.** `CampaignSent` arrives with PR 4, the first page with PR 3. The TS surface is `index.ts` (empty public API) and `ui/utils/i18n.ts` (copied from news), so that PR 3 starts with the i18n key tree already in place.
- **Ruling: settings carry no email-format validators** (`from_address`, `reply_to`). The framework replaces a settings class that will not construct with *all* defaults (ai's lesson), so a bad stored value would wipe every field. PR 3's page validates on save, and PR 4's send pre-flight refuses an incomplete sender.
- **Ruling: the extras `news` and `pagebuilder` are not declared yet.** They arrive with their first import in PR 3, each with its `# floor:` line. Only `simple_module_records` is a dependency now.
- **Ruling: newsletter's tests seed records through `sm_records.records.services`** (`type_service.create_type`, `record_service.create_record(system=…)`), the way records' own `tests/support/newsletter_contract.seed_list` does. That is a test-only import. Module code imports only `sm_records.contracts.*`.
- **Ruling: no admin landing page.** The framework does not need one, and a page would need a menu item and an Inertia dependency for nothing.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc or alembic run. If it exits 1, stop and report. Use `PYTEST_WORKERS=8` (`-n 8`) at most. Run **targeted tests only**: no full suite, no `make test-py`. The full suites run once, in `/ship`. Use `/usr/bin/ps`, never `ps`.
- Never run `ruff format` repo-wide. Use `uv run ruff format <the files you touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Run Python entry points from the repo root (`alembic.ini`, `.env`). Module tests run from their module directory: `cd modules/newsletter && uv run pytest …`.
- Pins: framework deps are ranges (`>=0.0.42,<0.1`), never `==`. `simple_module_records>=0.0.14,<0.1` with a `# floor:` comment naming the contract (PR 1 ships in the next lockstep release, 0.0.14). Version `0.0.13` in `pyproject.toml` and `package.json` (lockstep; `scripts/bump_version.py --check-current` must pass).
- Settings: `DbBackedSettings` (no env, `.env` or secrets sources), registered with `register_module_settings`, SYSTEM scope, no `requires_restart` field.
- Every table except `newsletter_dispatch_lock` carries `MultiTenantMixin`. Every write and read in module code pins `tenant_id` explicitly, because Core `INSERT … ON CONFLICT` is not stamped by the mixin's flush listener and an unbound read is unfiltered.
- Migrations: exactly one new revision in `host/migrations/versions/`, `branch_labels = ("newsletter",)`, `down_revision` = the single head at execution time (`c4e9b2a7d613` when this was written; re-check with `uv run python scripts/check_migration_heads.py`). `alembic check` must pass on SQLite and Postgres.
- 300-line cap per `.py`/`.ts`/`.tsx` (`scripts/check_file_size.py`). Keep files under 280.
- Locale files: `en.json` and `de.json` with identical key trees (`scripts/check_locales.py`).
- Commits: one per task, conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_017uTbtobjCKQYnAxF5tgK8t`.

## Review Focus

1. **Out-of-order events.** An `unsubscribed` event that arrives after the subscriber reconfirmed must write nothing, and a `confirmed` event for someone now unsubscribed must clear nothing. Tested in Task 7 (`test_stale_event_is_ignored`).
2. **Address spelling.** `" Ada@Example.ORG "` from an import or bounce and `"ada@example.org"` from records are one suppression. Tested in Task 6 (`test_hash_normalises_like_records`, `test_suppress_is_spelling_insensitive`).
3. **Confirmation clears too much.** It must keep `complaint` and keep another list's `unsubscribed` row. Tested in Task 6 (`test_clear_keeps_complaint_and_other_lists`) and Task 7.
4. **The mirror breaks records.** If the handler raises (DB down, a contract error), records' unsubscribe must still commit, and the failure must be logged and not raised. Tested in Task 7 (`test_handler_failure_never_breaks_records_write`).
5. **Reconcile across tenants.** One tenant's broken or vanished list must not stop the others. A second run inserts nothing. Tenant b's identical address is untouched by tenant a's unsubscribe. Tested in Task 8.

---

### Task 1: Package skeleton, workspace wiring, permissions

**Files:**
- Create: `modules/newsletter/pyproject.toml`, `modules/newsletter/package.json`, `modules/newsletter/tsconfig.json`, `modules/newsletter/README.md`, `modules/newsletter/NOTICE`, `modules/newsletter/docs/index.md`
- Create: `modules/newsletter/sm_newsletter/__init__.py` (docstring only), `sm_newsletter/module.py`, `sm_newsletter/core/__init__.py`, `sm_newsletter/core/constants.py`, `sm_newsletter/locales/en.json`, `sm_newsletter/locales/de.json`
- Create: `modules/newsletter/tests/__init__.py`, `tests/conftest.py`, `tests/pg_support.py`, `tests/core/__init__.py`, `tests/core/test_module_boot.py`
- Modify: `pyproject.toml` (root `testpaths`: add `"modules/newsletter/tests"` in sorted position), `host/pyproject.toml` (dependency `"simple_module_newsletter"`, plus `[tool.uv.sources.simple_module_newsletter] workspace = true`), `uv.lock`, `package-lock.json`

**Interfaces:**
- Produces `sm_newsletter.core.constants`:

```python
PACKAGE = "sm_newsletter"; MODULE_NAME = "Newsletter"; DISTRIBUTION = "simple_module_newsletter"
LOCALE_NAMESPACE = "newsletter"; TABLE_PREFIX = "newsletter_"; BASE_NAME = "newsletter"
ROUTE_PREFIX_API = "/api/newsletter"; VIEW_PREFIX = "/admin/newsletter"; PUBLIC_PREFIX = "/newsletter/"
PERM_GROUP = MODULE_NAME; PERM_GROUP_KEY = "newsletter.permission_group"
PERM_VIEW = "newsletter.view"; PERM_EDIT = "newsletter.edit"; PERM_SEND = "newsletter.send"; PERM_MANAGE = "newsletter.manage"
PERMISSIONS = (PERM_VIEW, PERM_EDIT, PERM_SEND, PERM_MANAGE)
_MODULE_SETTINGS = "Settings"; _MODULE_RECORDS = "Records"; _MODULE_BACKGROUND_TASKS = "BackgroundTasks"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_RECORDS, _MODULE_BACKGROUND_TASKS)
TENANT_REQUIRED_CODE = "tenant_required"; NOT_FOUND_DETAIL = "Not found"
```

- Produces `sm_newsletter.module.NewsletterModule(ModuleBase)`, with `meta` modelled on `ImagesModule.meta` (version from `importlib.metadata`, `requires_framework=">=1.0,<2.0"`), `register_permissions` (`add_group(PERM_GROUP, list(PERMISSIONS), label_key=PERM_GROUP_KEY)`) and `locale_dirs()`. Later tasks add hooks.
- `pyproject.toml`: entry point `[project.entry-points.simple_module] newsletter = "sm_newsletter.module:NewsletterModule"`. Dependencies are `simple_module_core`, `_db`, `_hosting`, `_settings`, `_background_tasks` (all `>=0.0.42,<0.1`), plus `cryptography>=42`, `pydantic-settings>=2.0`, and:

```toml
    # floor: 0.0.14 - sm_records.contracts.newsletter (iter_subscribers status walk,
    # subscribers_by_uuid, unsubscribe, set_tags, can_read_list) first ships in 0.0.14.
    "simple_module_records>=0.0.14,<0.1",
```

  `[tool.uv.sources] simple_module_records = { workspace = true }`. `dev` extra: `pytest>=8.0`, `pytest-asyncio>=0.24`, `simple_module_test>=0.0.42,<0.1`. Wheel/sdist config is images' (same `exclude` list, `artifacts`, `force-include` of `package.json`) with `sm_newsletter`. Keywords include `"simple-module"`, `"newsletter"`, `"email"`. `[tool.pytest.ini_options] asyncio_mode = "auto"` and the marker `unbound_tenant`.
- `package.json`: `"name": "@simple-module-py/newsletter"`, `"version": "0.0.13"`, `"private": true`, `"exports": {".": "./sm_newsletter/index.ts"}`, peerDependencies `@simple-module-py/i18n: "*"` and `react: "^19.3.1"`, devDependencies `@simple-module-py/tsconfig: "*"`. `tsconfig.json` is images' with `sm_newsletter`.
- Locales: `{"permission_group": "Newsletter"}` in both files (German is also "Newsletter").
- `tests/pg_support.py`: copy `modules/images/tests/pg_support.py`. `_extra_metadata()` returns `[sm_records.models.Base.metadata]` plus permissions' if installed. `make_db_state` uses `sm_newsletter.models.Base`, which exists from Task 5. Until then, import it lazily inside the function as images does. `tests/conftest.py` gets the `_default_tenant` autouse fixture (images' copy, using `sm_newsletter.core.tenancy` once Task 3 lands; until then `simple_module_db.tenant_context("default")`) and `_arm_database_reset` from images' conftest.

- [ ] **Step 1: Write the failing test** `tests/core/test_module_boot.py::test_module_registers_permissions`. Assert that `set(registry.all_permissions) == {"newsletter.view","newsletter.edit","newsletter.send","newsletter.manage"}`, that the single group has `name == "Newsletter"` and `label_key == "newsletter.permission_group"`, and that `"newsletter.settings"` is not registered. Add `test_locale_dir_is_the_namespace`: `NewsletterModule().locale_dirs()` has key `"newsletter"`, whose path contains `en.json` and `de.json`.
- [ ] **Step 2: Run it to see it fail.** Run `~/.claude/bin/wait-for-headroom`, then `uv sync --all-extras --no-extra anonymize` from the root, then `cd modules/newsletter && uv run pytest -q tests/core/test_module_boot.py`. Expected: `ModuleNotFoundError: sm_newsletter`, or a collection error until the package exists.
- [ ] **Step 3: Implement** the files above. Write the README per `scripts/check_readmes.py` (H1, ≥500 bytes, "Install" and "Usage" sections). It covers what the module does, that subscribers live in records, its settings and permissions, and that it has no routes yet. Then `docs/index.md` (status per roadmap PR, a link to the spec, a "Suppressions" section stating the scoping and hashing rulings). NOTICE reads `Copyright (c) Anto Subash. Licensed under the MIT License.`. Run `npm install` at the root so `package-lock.json` gains the workspace entry.
- [ ] **Step 4: Run the tests and the repo checks.** Same pytest command: passes. Then, from the root: `uv run python scripts/check_metadata.py`, `uv run python scripts/check_readmes.py`, `uv run python scripts/check_rules.py`, `uv run python scripts/check_locales.py`, `uv run python scripts/bump_version.py --check-current`. Each must pass.
- [ ] **Step 5: Commit** `feat(newsletter): module skeleton, workspace wiring and permissions`, with every file above plus `uv.lock` and `package-lock.json`.

### Task 2: Frontend i18n surface

**Files:**
- Create: `modules/newsletter/sm_newsletter/index.ts`, `sm_newsletter/ui/utils/i18n.ts`, `sm_newsletter/ui/utils/i18n.test.ts`

**Interfaces:**
- `ui/utils/i18n.ts` is `modules/news/news/ui/utils/i18n.ts` with `NAMESPACE = 'newsletter'` and the doc comment's module names changed. It exports `keys`, `translate`, `useT`, `Translate` and `TranslateParams`. `index.ts` holds a doc comment ("the public TS surface; empty until a sibling needs something") and `export {};`.

- [ ] **Step 1: Write the failing test** `i18n.test.ts`. `keys.newsletter.permission_group` equals `'newsletter.permission_group'`, and `translate('newsletter.permission_group')` equals `'Newsletter'`, as the vitest setup configures the catalogue.
- [ ] **Step 2: Run it to see it fail.** Run `~/.claude/bin/wait-for-headroom`, then `npx vitest run modules/newsletter`. Expected: cannot resolve `./i18n`.
- [ ] **Step 3: Implement** both files.
- [ ] **Step 4: Run.** `npx vitest run modules/newsletter` passes. `npx tsc --noEmit -p modules/newsletter/tsconfig.json` passes. `npx biome check modules/newsletter` passes.
- [ ] **Step 5: Commit** `feat(newsletter): i18n key tree and TS entry point`.

### Task 3: Tenancy and errors

**Files:**
- Create: `sm_newsletter/core/tenancy/__init__.py`, `core/tenancy/_mode.py`, `core/tenancy/_guard.py` (copies of `modules/images/sm_images/core/tenancy/{__init__,_mode,_guard}.py`, with `sm_images`/`images` changed to `sm_newsletter`/`newsletter`, `ALL_TENANTS = "newsletter_all_tenants"`, `_UPSTREAM_ATTR = "newsletter_tenant_from_request"`, and the guard's owned-table check against `newsletter_`)
- Create: `sm_newsletter/core/errors.py`
- Create: `tests/core/tenancy/__init__.py`, `tests/core/tenancy/test_tenancy.py`
- Modify: `scripts/tests/parity_tenancy.py` (add `NEWSLETTER = "modules/newsletter/sm_newsletter"` and a `Copy` of each file to the families "tenancy mode detection: records" (`{"logger": "_log"}`) and "tenancy binding: records" (`{"_resolved": "upstream_tenant"}`); the existing `differ` texts already cover images, so extend their wording to "images' and newsletter's" where they name images), `scripts/tests/parity_families.py` (add `Copy("modules/newsletter/tests/pg_support.py")` to "test scaffolding: Postgres opt-in"), `host/tests/test_tenancy_parity.py` (add `"newsletter": sm_newsletter.core.tenancy._mode` and `sm_newsletter.core.tenancy` to `_DETECTORS`/`_RESOLVERS`)
- Modify: `tests/conftest.py` (`_default_tenant` uses `sm_newsletter.core.tenancy.tenant_scope(DEFAULT_TENANT)`)

**Interfaces:**
- `sm_newsletter.core.errors`: `NewsletterError(Exception)` with `status: int`, `code: str`, `detail: str`; `NotFound` (404, `not_found`); `Forbidden` (403, `forbidden`); `TenantRequired(Forbidden)` (code `tenant_required`); `SmtpPasswordUnreadable(NewsletterError)` (500, `smtp_password_unreadable`, raised by Task 4); `install_exception_handlers(app)`, which renders `{"detail": …, "code": …}` as JSON (images' `render` without the HTML error page).
- `sm_newsletter.core.tenancy` exports what images' exports: `DEFAULT_TENANT`, `TenancyMode`, `TenantUnbound`, `valid_tenant`, `tenant_scope`, `bound_tenant`, `resolve_admin`, `resolve_public`, `bind_admin`, `bind_public`, `all_tenants(stmt)`, `install_guard`, `configure`, `mode_of`, `request_mode`, `view_props`, `note_tenant_source`, `tenant_from_request`. Drop `request_context` (images-only).

- [ ] **Step 1: Write the failing tests** in `test_tenancy.py`:
  - `test_scope_refuses_a_second_tenant`: inside `tenant_scope("a")`, `tenant_scope("b")` raises `TenantIsolationError`, and `tenant_scope("a")` is a no-op re-entry.
  - `test_invalid_tenant_refused`: `tenant_scope("bad tenant!")` raises `ValueError`.
  - `test_admin_single_mode_binds_default` and `test_admin_multi_without_tenant_is_403`: build a FastAPI app with `configure(app)` stubbed to SINGLE/MULTI, as in images' `tests/core` tenancy tests (`grep -rn "def test_.*resolve_admin\|TenantRequired" modules/images/tests`). The MULTI case returns 403 with body `{"detail": …, "code": "tenant_required"}` through `install_exception_handlers`.
  - `test_public_without_tenant_is_none`: `resolve_public` returns `None` in multi mode with nothing resolved.
  - `test_upstream_tenant_wins_in_single_mode`: `request.state.tenant_id = "acme"` resolves to `"acme"` for both resolvers.
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/tenancy`. Expected: `ModuleNotFoundError: sm_newsletter.core.tenancy`.
- [ ] **Step 3: Implement** the copies and `errors.py`.
- [ ] **Step 4: Run** the same command: passes. Then, from the root, `uv run pytest -q scripts/tests/test_helper_parity.py host/tests/test_tenancy_parity.py`: passes.
- [ ] **Step 5: Commit** `feat(newsletter): tenancy copy and error envelope`.

### Task 4: Settings, password crypto and the services container

**Files:**
- Create: `sm_newsletter/core/settings/__init__.py` (`NewsletterSettings`), `sm_newsletter/core/crypto.py`, `sm_newsletter/core/services.py`
- Modify: `sm_newsletter/module.py` (`register_settings`, `register_exception_handlers`)
- Modify: `scripts/tests/parity_families.py` (new family "stored-secret crypto": `Copy("modules/ai/sm_ai/core/crypto.py")` and `Copy("modules/newsletter/sm_newsletter/core/crypto.py")`, `shared=("ENC_PREFIX", "set_secret_provider", "_fernet_for", "explicit_secret", "_dotenv_secret", "encrypt_value")`, `differ={"decrypt_value": "Each module raises its own unreadable-secret error.", "_fernet": "Each names its own module in the missing-secret message."}`)
- Test: `tests/core/test_settings.py`, `tests/core/test_crypto.py`

**Interfaces:**
- `NewsletterSettings(DbBackedSettings)`, `model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)`, with every field documented by an attribute docstring (the Settings screen shows it):

| field | type | default |
|---|---|---|
| `transport` | `Literal["smtp", "console"]` | `"smtp"` |
| `smtp_host` | `str` | `"smtp-relay.gmail.com"` |
| `smtp_port` | `int`, `ge=1, le=65535` | `587` |
| `smtp_security` | `Literal["starttls", "tls"]` | `"starttls"` |
| `smtp_username` | `str` | `""` |
| `smtp_password` | `str`, `Field(repr=False)` | `""` (stored `enc:v1:…`) |
| `from_address`, `from_name`, `reply_to` | `str` | `""` |
| `daily_limit` | `int`, `ge=1` | `9500` |
| `per_minute_limit` | `int`, `ge=1` | `30` |
| `tracking_opens`, `tracking_clicks` | `bool` | `True` |
| `physical_address` | `str` | `""` |

- `sm_newsletter.core.crypto`: copy of `sm_ai.core.crypto`, with `ENC_PREFIX = "enc:v1:"`, `set_secret_provider(provider)`, `encrypt_value(plain) -> str` and `decrypt_value(stored, field) -> str`. `decrypt_value` raises `SmtpPasswordUnreadable` on `InvalidToken`, and treats a value without the prefix as plaintext with one warning per field. Add `smtp_password(settings: NewsletterSettings) -> str = decrypt_value(settings.smtp_password, "smtp_password")`.
- `sm_newsletter.core.services.NewsletterServices`, a dataclass with `settings: NewsletterSettings`.
- `NewsletterModule.register_settings(app)`: `register_module_settings(app, PACKAGE, NewsletterSettings, lambda s: NewsletterServices(settings=self.settings or s))`, with no `manage_url` (Ruling), then `crypto.set_secret_provider(...)` through a weakref to `app`, reading `app.state.sm.settings.secret_key` exactly as `AiModule.register_settings` does. `__init__` sets `self.settings = None`, so a test can pin settings, as images does.

- [ ] **Step 1: Write the failing tests.**
  - `test_defaults_match_the_spec`: every default in the table above.
  - `test_settings_ignore_env`: with `SM_NEWSLETTER_DAILY_LIMIT=1` and `DAILY_LIMIT=1` set, `NewsletterSettings().daily_limit == 9500`.
  - `test_no_field_needs_a_restart`: no field's `json_schema_extra` has `requires_restart`.
  - `test_password_never_in_repr`: `"secret" not in repr(NewsletterSettings(smtp_password="secret"))`.
  - `test_register_settings_mounts_services`: on a bare `FastAPI()` with a `ModuleSettingsRegistry` on `app.state` (as in images' `tests/core/test_module_boot.py`), `app.state.sm_newsletter.settings` is a `NewsletterSettings`.
  - `test_crypto.py::test_round_trip` (with `SM_SECRET_KEY` monkeypatched): `decrypt_value(encrypt_value("pw"), "smtp_password") == "pw"`, and the stored value starts with `enc:v1:`. `test_plaintext_tolerated_and_warned_once`: `"pw"` comes back as `"pw"`, with one warning across two calls (`caplog`). `test_other_secret_is_unreadable`: encrypt under key A and decrypt under key B raises `SmtpPasswordUnreadable`. `test_missing_secret_raises`: no secret anywhere raises `RuntimeError` (monkeypatch `_dotenv_secret` to return `""`).
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/test_settings.py tests/core/test_crypto.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command, plus `uv run pytest -q scripts/tests/test_helper_parity.py` from the root: passes.
- [ ] **Step 5: Commit** `feat(newsletter): DB-backed settings with encrypted SMTP password`.

### Task 5: Models and the migration

**Files:**
- Create: `sm_newsletter/models/__init__.py` (imports every table; `__all__`), `models/_base.py` (`Base = create_module_base(BASE_NAME)`), `models/_cols.py`, `models/mailing_list.py`, `models/campaign.py`, `models/segment.py`, `models/send.py`, `models/link.py`, `models/suppression.py`, `models/dispatch_lock.py`
- Create: `sm_newsletter/core/clock/__init__.py` (`utcnow() -> datetime`, aware UTC)
- Create: `sm_newsletter/core/constants.py` additions (below)
- Create: `host/migrations/versions/<rev>_add_newsletter.py` (autogenerated)
- Modify: `tests/conftest.py` (fixtures `db_state` → `await make_db_state()`, disposed after; `db` → one session from it)
- Test: `tests/core/test_models.py`, `host/tests/test_newsletter_wiring.py`

**Interfaces:**
- Constants: `CAMPAIGN_STATUSES = ("draft","scheduled","sending","paused","sent","cancelled")`, `SEND_STATUSES = ("queued","sending","sent","failed","bounced","suppressed","skipped_unsubscribed","cancelled")`, `ATTEMPT_KINDS = ("campaign","test")`, `ATTEMPT_OUTCOMES = ("pending","accepted","rejected","unknown")`, `REASON_HARD_BOUNCE="hard_bounce"`, `REASON_COMPLAINT="complaint"`, `REASON_IMPORTED_CLEANED="imported_cleaned"`, `REASON_UNSUBSCRIBED="unsubscribed"`, `REASONS` (all four), `CLEARED_BY_CONFIRMATION = (REASON_HARD_BOUNCE, REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED)`, `SOURCES = ("records_event","reconcile","unsubscribe_page","send","import","admin")`, `MAX_TYPE_KEY_LEN = 64` (records' `MAX_KEY_LEN`), `MAX_EMAIL_LEN = 320`.
- `_cols.py`: `big_pk()` → `Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))` (billing's precedent; a plain `BigInteger` key does not autoincrement on SQLite). `dt_col(*, index=False, nullable=True)` uses `AwareDateTime()`. `json_col(default_factory)` is images'. Each `fk(target, *, ondelete, nullable=False)` is an `Integer`/`BigInteger` FK with `index=True`.
- Tables. All are `Base, MultiTenantMixin, table=True` except `DispatchLock`. Statuses are `str` with `max_length=24`.
  - `NewsletterList` `newsletter_list`: `id` int PK; `type_key` (64); `created_at` (not null, default `utcnow`); `last_reconciled_at` (nullable). Unique `uq_newsletter_list_tenant_type (tenant_id, type_key)`.
  - `Campaign` `newsletter_campaign` (`+ AuditMixin`): `id` int PK; `name` (200); `subject` (300, default `""`); `preheader` (300, default `""`); `from_name` (200, nullable); `reply_to` (320, nullable); `body` JSON list (default `[]`); `list_type_key` (64); `audience` (140, default `"all"`); `status` (default `"draft"`); `paused_reason` (1000, nullable); `scheduled_at`, `started_at`, `finished_at` (nullable). Counters (int, default 0, not null): `recipient_count`, `sent_count`, `failed_count`, `bounced_count`, `suppressed_count`, `open_unique_count`, `open_total_count`, `click_unique_count`, `click_total_count`, `unsubscribe_count`. Indexes `ix_newsletter_campaign_tenant_status (tenant_id, status)` and `ix_newsletter_campaign_status_started (status, started_at)` (the dispatcher's oldest-first scan).
  - `Segment` `newsletter_segment` (`+ AuditMixin`): `id` int PK; `name` (200); `list_type_key` (64); `filters` JSON list of str (default `[]`). Unique `uq_newsletter_segment_name (tenant_id, list_type_key, name)`.
  - `Send` `newsletter_send`: `id` big PK; `campaign_id` FK `newsletter_campaign.id` `ondelete="CASCADE"`; `record_uuid` (32); `email` (320); `status` (default `"queued"`); `attempts` int 0; `lease_until`, `sent_at`, `opened_at`, `first_clicked_at` (nullable); `open_count` int 0; `last_error` (1000, nullable); `error_kind` (24, nullable). Unique `uq_newsletter_send_campaign_record (campaign_id, record_uuid)`, the spec's no-duplicate guarantee. Index `ix_newsletter_send_campaign_status (campaign_id, status, id)`.
  - `SendAttempt` `newsletter_send_attempt` (amendment 4's ledger): `id` big PK; `send_id` FK `newsletter_send.id` `ondelete="SET NULL"`, nullable (a test send has none); `campaign_id` FK `newsletter_campaign.id` `ondelete="SET NULL"`, nullable; `kind` (8); `recipient` (320); `attempted_at` (not null); `outcome` (16, default `"pending"`); `smtp_code` int nullable; `detail` (500, nullable). Index `ix_newsletter_send_attempt_at (attempted_at)`. One row per recipient per SMTP attempt.
  - `Link` `newsletter_link`: `id` int PK; `campaign_id` FK cascade; `position` int; `url` (2048). Unique `uq_newsletter_link_position (campaign_id, position)`.
  - `Click` `newsletter_click`: `id` big PK; `send_id` FK `newsletter_send.id` cascade; `link_id` FK `newsletter_link.id` cascade; `clicked_at` (not null). Both FKs are indexed.
  - `Suppression` `newsletter_suppression`: `id` big PK; `email_hash` (64); `reason` (24); `list_type_key` (64, not null, default `""`); `source` (24); `created_at` (not null). Unique `uq_newsletter_suppression (tenant_id, email_hash, reason, list_type_key)`. Index `ix_newsletter_suppression_lookup (tenant_id, email_hash)`.
  - `DispatchLock` `newsletter_dispatch_lock`. **No** `MultiTenantMixin`: one budget for the whole install (amendment 4, SQLite path), the same reasoning as `images_upload_admission`. Columns: `name` (32) PK; `holder` (64, nullable); `locked_until` (nullable); `updated_at` (not null). PR 4 upserts the singleton row `"dispatch"` on first use. No data migration.

- [ ] **Step 1: Write the failing tests** `tests/core/test_models.py`:
  - `test_one_send_per_recipient_per_campaign`: two `Send(campaign_id=c.id, record_uuid="u1", email=…)` raise `IntegrityError` on flush.
  - `test_big_ids_autoincrement`: two sends flush with ids `a` and `b`, where `b > a > 0`. This runs on both backends.
  - `test_suppression_unique_per_reason_and_list`: the same `(hash, "unsubscribed", "news")` twice fails. The same hash with `"other"` as the list, or with `"complaint"` and `""`, is accepted.
  - `test_tenant_stamped_from_scope`: a `Campaign` flushed under the autouse `default` scope has `tenant_id == "default"`.
  - `test_only_the_lock_is_global`: every table in `Base.metadata.tables` except `newsletter_dispatch_lock` has a `tenant_id` column, and every name starts with `newsletter_`.
  - `host/tests/test_newsletter_wiring.py::test_host_metadata_has_newsletter_tables`: `simple_module_db.build_module_metadata().tables` contains all nine names. `test_host_loads_the_module`: `create_app(Settings())` from `simple_module_hosting` has a module whose `meta.name == "Newsletter"`.
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/test_models.py`, and `uv run pytest -q host/tests/test_newsletter_wiring.py` from the root.
- [ ] **Step 3: Implement** the models.
- [ ] **Step 4: Generate the revision against a scratch SQLite database** (never `host/app.db`). From the root, with `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/newsletter-mig.db` exported for each command: `uv run --project host alembic -c host/alembic.ini upgrade heads`, then `uv run --project host alembic -c host/alembic.ini revision --autogenerate -m "add newsletter"`. Open the file. Set `branch_labels = ("newsletter",)`. Confirm that `down_revision` is the prior single head, that it creates exactly the nine `newsletter_*` tables and their indexes, and that it alters or drops nothing else. Delete any unrelated drift it picked up and report it rather than ship it. Write a docstring that says what the revision creates, as the other revisions do. Then `upgrade heads`, `alembic check` (expected: "No new upgrade operations detected"), `downgrade <parent rev>`, `upgrade heads`, `check` again. Delete `/tmp/newsletter-mig.db`.
- [ ] **Step 5: Postgres.** Using dev-services' Postgres (`make up` in dev-services if it is down; do not start a per-project container), create a scratch database with `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_check` (or `docker exec` into the dev-services container with `psql -c "CREATE DATABASE smpy_newsletter_check"`). With `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_check`, run `upgrade heads`, `check`, `downgrade base`, `upgrade heads`, `check`. All must pass. Drop the scratch database afterwards. It is not shared data, but say in the summary that you dropped it.
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (expected: one head, the new revision). Then run the Step 2 tests: pass. Then run `cd modules/newsletter && SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test uv run pytest -q tests/core/test_models.py` (create that database first): passes on Postgres.
- [ ] **Step 7: Commit** `feat(newsletter): every newsletter table and its migration`.

### Task 6: Suppression store, hashing and the list registry

**Files:**
- Create: `sm_newsletter/core/suppression/__init__.py` (docstring: the rulings on scoping and hashing), `core/suppression/hashing.py`, `core/suppression/store.py`, `core/lists.py`, `core/upsert.py`
- Test: `tests/core/suppression/__init__.py`, `tests/core/suppression/test_hashing.py`, `tests/core/suppression/test_store.py`, `tests/core/test_lists.py`

**Interfaces:**

```python
# core/suppression/hashing.py
def normalise_email(address: str) -> str          # address.strip().lower(); "" or non-str -> ValueError
def email_hash(address: str) -> str               # sha256(normalise_email(address).encode()).hexdigest()

# core/upsert.py
async def insert_ignore(session, table: Table, rows: Sequence[dict], *, conflict: Sequence[str]) -> int
    # sqlite / postgresql dialect insert(...).on_conflict_do_nothing(index_elements=conflict);
    # returns rows inserted (result.rowcount); ValueError for another dialect

# core/suppression/store.py   (every function: tenant_id validated, bound with tenant_scope, pinned in WHERE / VALUES)
async def suppress(session, *, tenant_id: str, email: str, reason: str, source: str,
                   list_type_key: str = "") -> bool
    # True if this call inserted; reason == "unsubscribed" requires a list_type_key, every
    # other reason requires "" (ValueError otherwise); unknown reason/source -> ValueError
async def suppress_many(session, *, tenant_id: str, emails: Sequence[str], reason: str,
                        source: str, list_type_key: str = "") -> int
async def clear_for_confirmation(session, *, tenant_id: str, email: str, list_type_key: str) -> int
    # deletes (reason="unsubscribed", list_type_key=list) and (reason in hard_bounce,
    # imported_cleaned, list_type_key=""); never complaint; returns rows deleted
async def suppressed(session, *, tenant_id: str, list_type_key: str,
                     emails: Sequence[str]) -> set[str]
    # the normalised addresses among `emails` with any row whose list_type_key in ("", list)

# core/lists.py
async def register_list(session, *, tenant_id: str, type_key: str) -> bool
async def registered_lists(session) -> list[tuple[str, str]]
    # (tenant_id, type_key) for every tenant: one read under the framework's all_tenants()
    # and sm_newsletter.core.tenancy.all_tenants(stmt), as sm_images.jobs.reconcile.tenants does;
    # invalid tenant ids dropped
async def mark_reconciled(session, *, tenant_id: str, type_key: str, at: datetime) -> None
```

None of these commit. Callers finish with `simple_module_db.finalize_session`.

- [ ] **Step 1: Write the failing tests.**
  - `test_hash_normalises_like_records`: `email_hash(" Ada@Example.ORG ") == email_hash("ada@example.org") == hashlib.sha256(b"ada@example.org").hexdigest()`. `normalise_email("")` and `normalise_email(None)` raise `ValueError`.
  - `test_suppress_is_idempotent`: the first call returns `True`, the second `False`, and there is one row.
  - `test_suppress_is_spelling_insensitive`: suppress `"ADA@example.org"`, then `suppressed(..., emails=[" ada@example.org"])` gives `{"ada@example.org"}`.
  - `test_reason_and_list_must_agree`: `reason="unsubscribed", list_type_key=""` and `reason="complaint", list_type_key="news"` each raise `ValueError`, and so does an unknown reason.
  - `test_list_and_address_wide_rows_both_suppress`: an `unsubscribed` row on `"news"` suppresses for `"news"` but not for `"other"`. A `hard_bounce` row suppresses for both.
  - `test_clear_keeps_complaint_and_other_lists`: seed `unsubscribed/news`, `unsubscribed/other`, `hard_bounce`, `imported_cleaned` and `complaint`. `clear_for_confirmation(list_type_key="news")` returns `3`, leaving `unsubscribed/other` and `complaint`.
  - `test_tenant_isolation`: a row in tenant `a` is invisible to `suppressed(tenant_id="b")`, and `clear_for_confirmation(tenant_id="b")` deletes `0`. Mark the test `unbound_tenant`, with one session per tenant scope.
  - `test_lists.py`: `register_list` returns `True` then `False`. `registered_lists` returns both tenants' rows from an unbound context and runs inside `no_tenant()`.
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/suppression tests/core/test_lists.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite, then with `SM_TEST_DATABASE_URL` set to the Postgres test database (the dialect switch in `insert_ignore` is what differs). Both pass.
- [ ] **Step 5: Commit** `feat(newsletter): suppression store and list registry`.

### Task 7: The `SubscriptionChanged` mirror

**Files:**
- Create: `sm_newsletter/core/suppression/mirror.py`
- Modify: `sm_newsletter/module.py` (`register_event_handlers`, `on_startup`)
- Create: `tests/support/__init__.py`, `tests/support/records_seed.py`
- Test: `tests/core/suppression/test_mirror.py`

**Interfaces:**
- Consumes: Task 6's store and lists. From `sm_records.contracts.newsletter`, `subscribers_by_uuid`, `SubscriberFilterError` and (in tests) `unsubscribe`. From `sm_records.contracts.events`, `SubscriptionChanged`.
- Produces:

```python
# core/suppression/mirror.py
async def apply(event: SubscriptionChanged, session_factory: Callable[[], AsyncSession]) -> str
    # returns what it did: "suppressed" | "cleared" | "registered" | "ignored"
    # one session, bound with tenant_scope(event.tenant_id); register_list first (every status);
    # hit = subscribers_by_uuid(...)[event.uuid]; acts only when hit.status == event.status_after:
    #   "unsubscribed" -> suppress(reason=unsubscribed, list_type_key=event.type_key, source="records_event")
    #   "confirmed" and not hit.trashed -> clear_for_confirmation(list_type_key=event.type_key)
    # SubscriberFilterError (not a list) -> "ignored"; finalize_session at the end
def subscribe(bus: EventBus, app: FastAPI) -> None
    # bus.subscribe(SubscriptionChanged, handler); handler reads app.state.sm.db.session_factory
    # at event time, calls apply, and logs (logger.warning(..., exc_info=True)) instead of raising
```

- `NewsletterModule.register_event_handlers(bus, app=None)`: `if app is None: return` (the outbox worker builds modules without an app, and this handler needs the web session factory), then `mirror.subscribe(bus, app)`.
- `NewsletterModule.on_startup(app)`: `tenancy.configure(app)`, then `tenancy.install_guard(app.state.sm.db.sync_session_class)` when present, as images does.
- `tests/support/records_seed.py`:

```python
LIST = "news"
async def seed_list(db_state, tenant: str, key: str = LIST) -> None
    # type_service.create_type(key=key, label=key, fields_raw=[],
    #   public_submissions={"kind": "subscription", "enabled": True}, settings=RecordsSettings())
async def seed_subscriber(db_state, tenant: str, email: str, status: str, key: str = LIST,
                          *, trashed: bool = False) -> str   # uuid
    # record_service.create_record(system={"sm_email", "sm_status", "sm_confirmed_at" (confirmed only),
    #   "sm_locale": "en", "sm_nonce": secrets.token_hex(16)}); soft_delete_record if trashed;
    #   finished with sm_records.core.events.commit
```

- [ ] **Step 1: Write the failing tests** (`db_state` fixture, `records_seed` helpers, and `RecordsSettings()`):
  - `test_unsubscribe_event_suppresses`: seed an `unsubscribed` subscriber, then `apply(SubscriptionChanged(type_key="news", tenant_id="default", uuid=u, status_before="confirmed", status_after="unsubscribed"), db_state.session_factory)` returns `"suppressed"`. The `unsubscribed/news` row exists with `source == "records_event"`.
  - `test_confirm_event_clears_but_keeps_complaint`: seed a `confirmed` subscriber plus `unsubscribed/news`, `hard_bounce` and `complaint` rows for its address. The confirmed event returns `"cleared"` and leaves only `complaint`.
  - `test_stale_event_is_ignored`: a `confirmed` subscriber with an `unsubscribed` event returns `"registered"` and writes no suppression. An `unsubscribed` subscriber with a `confirmed` event clears nothing.
  - `test_pending_registers_only`: a `pending` event registers the list (`registered_lists` contains `("default","news")`) and touches no suppression.
  - `test_trashed_unsubscribed_still_mirrored` and `test_trashed_confirmed_clears_nothing`.
  - `test_unknown_uuid_is_harmless`: the result is `"registered"`, with no row and no error.
  - `test_real_unsubscribe_reaches_the_mirror`: build `bus = EventBus()` and `app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=db_state, event_bus=bus)))`, then `NewsletterModule().register_event_handlers(bus, app)`. Seed a confirmed subscriber. In a session, `await unsubscribe(s, tenant_id="default", type_key="news", uuid=u, unless_confirmed_after=None, settings=RecordsSettings(), bus=bus)`, then `await finalize_session(s)`. Afterwards the suppression row exists. This is the real records → bus → handler path.
  - `test_handler_failure_never_breaks_records_write`: the same setup, but `app.state.sm.db` is a stub whose `session_factory` raises `RuntimeError`. The `unsubscribe` plus `finalize_session` completes, records reads the subscriber back as `unsubscribed`, and `caplog` holds one warning from `sm_newsletter`.
  - `test_no_app_registers_nothing`: `register_event_handlers(bus, None)` leaves `bus` with no `SubscriptionChanged` subscriber. Check this by publishing one and asserting that nothing is written.
  - `test_tenant_isolation` (`unbound_tenant`): the same address is subscribed in tenants `a` and `b`. An `unsubscribed` event in `a` writes a row in `a` only.
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/suppression/test_mirror.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and on Postgres. Both pass.
- [ ] **Step 5: Commit** `feat(newsletter): mirror records unsubscribes into suppressions`.

### Task 8: The hourly reconcile, worker runtime and task wiring

**Files:**
- Create: `sm_newsletter/core/suppression/reconcile.py`, `sm_newsletter/core/worker.py`, `sm_newsletter/tasks.py`, `sm_newsletter/task_config.py`
- Modify: `Makefile` (the `worker` target's queues become `-Q images,newsletter,celery`, and the comment above it names newsletter)
- Test: `tests/core/suppression/test_reconcile.py`, `tests/core/test_task_discovery.py`

**Interfaces:**

```python
# task_config.py
RECONCILE_SUPPRESSIONS = "newsletter.reconcile_suppressions"
QUEUE_DEFAULT = "newsletter"
TASK_ROUTES = {RECONCILE_SUPPRESSIONS: {"queue": QUEUE_DEFAULT}}
RECONCILE_INTERVAL_SECONDS = 3600.0
BEAT_SCHEDULE = {"newsletter-reconcile-suppressions": {"task": RECONCILE_SUPPRESSIONS,
                 "schedule": RECONCILE_INTERVAL_SECONDS, "options": {"queue": QUEUE_DEFAULT}}}

# core/suppression/reconcile.py
async def reconcile_async(session_factory, *, now: datetime) -> dict[str, int]
    # {"lists": n, "suppressed": inserted, "failed": lists that raised}
    # registered_lists() in one unscoped read; then per (tenant, type_key), under tenant_scope
    # and in a fresh session per page: iter_subscribers(status="unsubscribed",
    # limit=MAX_SUBSCRIBER_BATCH, after=cursor) -> suppress_many(reason=unsubscribed,
    # list_type_key=type_key, source="reconcile") -> finalize_session; then mark_reconciled(at=now).
    # A list that raises (SubscriberFilterError or anything else) is logged, counted in "failed",
    # and the loop goes on. Never clears a row.

# core/worker.py   (sm_images.pipeline.worker_runtime trimmed to the DB part)
def worker_session_factory() -> async_sessionmaker   # per-pid NullPool engine from background_tasks.sync_db,
                                                      # session listeners, engine tenancy policy, install_guard
def reset_worker_runtime() -> None
def run_platform[T](body: Callable[[Any], Awaitable[T]]) -> T   # refuses a running loop; no_tenant(); asyncio.run

# tasks.py
@shared_task(name=RECONCILE_SUPPRESSIONS)
def reconcile_suppressions() -> dict[str, int]
    # run_platform(lambda factory: reconcile_async(factory, now=utcnow())); logs a non-empty summary
# plus worker_process_init -> reset_worker_runtime (dispatch_uid "sm_newsletter.forget_parent_runtime")
```

- [ ] **Step 1: Write the failing tests.**
  - `test_reconcile_suppresses_unsubscribed`: register `news`, then seed two `unsubscribed` subscribers and one `confirmed`. `reconcile_async(db_state.session_factory, now=T)` returns `{"lists": 1, "suppressed": 2, "failed": 0}`, writes rows with `source == "reconcile"`, and sets `last_reconciled_at == T`.
  - `test_reconcile_is_idempotent`: a second run gives `"suppressed": 0`.
  - `test_reconcile_never_clears`: an existing `hard_bounce` row for a confirmed subscriber survives.
  - `test_reconcile_pages`: monkeypatch the page size to 1, seed three unsubscribed subscribers, and all three are suppressed.
  - `test_one_bad_list_does_not_stop_others` (`unbound_tenant`): tenant `a` registers `news` and has one unsubscribed subscriber. Tenant `b` registers `"form"`, whose records type is kind `form`, so the contract raises `not_a_list`. The result is `{"lists": 2, "suppressed": 1, "failed": 1}` and `caplog` has a warning.
  - `test_reconcile_tenant_isolation` (`unbound_tenant`): with the same address in both tenants and unsubscribed only in `a`, only `a` gets a row.
  - `test_task_discovery.py` (images' shape): `sm_newsletter.tasks` defines a task named `RECONCILE_SUPPRESSIONS`. `background_tasks.task_routing.load_task_config("sm_newsletter")` returns `routes == TASK_ROUTES` and `beat_schedule == BEAT_SCHEDULE`. The beat interval is `3600.0`.
- [ ] **Step 2: Run to see them fail.** `cd modules/newsletter && uv run pytest -q tests/core/suppression/test_reconcile.py tests/core/test_task_discovery.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and Postgres. Then confirm that each new file imports on its own: `uv run python -c "import sm_newsletter.tasks, sm_newsletter.task_config, sm_newsletter.core.worker, sm_newsletter.core.suppression.reconcile, sm_newsletter.core.suppression.mirror, sm_newsletter.module"` run from the root with a fresh interpreter (expected: exit 0).
- [ ] **Step 5: Commit** `feat(newsletter): hourly suppression reconcile`.

### Task 9: CI, repo docs and branch verification

**Files:**
- Modify: `.github/workflows/ci.yml`. Add `ci_newsletter` to the `createdb` loop, and add a step `Run pytest (newsletter, Postgres)` after the images one (`if: ${{ !cancelled() }}`, `SM_TEST_DATABASE_URL: …/ci_newsletter`, `run: scripts/pytest_modules.sh newsletter`). The upsert and the cross-tenant read differ by dialect.
- Modify: `README.md`, adding a modules-table row for `modules/newsletter` / `simple_module_newsletter`.
- Modify: `docs/module-layout.md` ("All six modules" becomes "All seven").
- Modify: `CLAUDE.md`, minimally. Add newsletter to the tenancy rule's module list (with `sm_newsletter.core.tenancy` as a copy of images'), to the "read no environment variables" list, and to "All six modules follow it" (now seven). Add one sentence under the records-subscribers area: newsletter mirrors unsubscribes into `newsletter_suppression` (event plus hourly reconcile), and a confirmation never clears `complaint`.
- Modify: `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`. PR 2's row gains "the hourly suppression reconcile"; PR 4's row drops it.

- [ ] **Step 1:** Run `~/.claude/bin/wait-for-headroom`, then the lint set from the root: `uv run ruff check modules/newsletter scripts host`, `uv run ruff format --check modules/newsletter host/tests/test_newsletter_wiring.py`, `uv run python scripts/check_file_size.py`, `uv run python scripts/check_rules.py`, `uv run python scripts/check_metadata.py`, `uv run python scripts/check_readmes.py`, `uv run python scripts/check_locales.py`, `uv run python scripts/check_hardcoded_strings.py`, `uv run python scripts/check_migration_heads.py`, `npx biome check modules/newsletter` and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`. All pass. A WARNING at 280+ lines means split the file now.
- [ ] **Step 2:** Run the targeted suites, one at a time. First the newsletter suite on SQLite: `cd modules/newsletter && uv run pytest -q -n 8`. Then the same with `SM_TEST_DATABASE_URL` set to Postgres. Then, from the root, `uv run pytest -q -n 8 scripts/tests host/tests/test_tenancy_parity.py host/tests/test_newsletter_wiring.py host/tests/test_host_boots.py`. Then `npx vitest run modules/newsletter`. All pass. Do **not** run the full records or host suites; `/ship` does.
- [ ] **Step 3: Commit** `chore(newsletter): CI Postgres job, docs and roadmap`.

## Amendments from the Codex plan review (2026-11-03)

These override any task text above that contradicts them.

1. **Unsubscribe suppressions are tenant-wide, not per list** (overrides the per-list ruling). An
   unsubscribe on any list suppresses the address for every list in the tenant, so a later import
   into another list cannot make it mailable (spec "suppression wins"). Keep `list_type_key` on the
   row only as provenance; it is not part of the uniqueness key or the lookup.
2. **Clearing on confirmation takes a cutoff.** The mirror reads the subscriber's `confirmed_at`
   through `subscribers_by_uuid` and deletes only `unsubscribed`/`hard_bounce`/`imported_cleaned`
   rows with `created_at <= confirmed_at` (never `complaint`). A repeated opt-out or bounce on an
   existing row refreshes its `created_at`, so a newer suppression always survives a delayed
   handler. Test: confirm, then bounce, then the delayed confirm handler runs -> bounce kept.
3. **No `newsletter_list` registry table.** Records gets a tenant-pinned contract
   `subscription_lists(session, *, tenant_id) -> list[str]` (type keys of kind `subscription`,
   live types only) in `sm_records.contracts.newsletter`, tested in records. The reconcile walks
   every list it returns. Drop the registry model, its migration table and `register_list`.
4. **Records floor:** `simple_module_records>=0.0.13` (the workspace version) with
   `# floor: 0.0.13 — raise to the release that first ships contracts.newsletter (#306) when it is cut`.
   A `>=0.0.14` floor cannot resolve in the workspace; the version bump is a release action, not
   this PR's.
5. **`smtp_password` is never persisted in plaintext.** Copy ai's pattern: generic Settings-screen
   writes of the field are refused (see `modules/ai/sm_ai/core/settings.py` and how ai stores keys
   via `sm_ai/web/service.py`), and PR 2 adds the one write path: an admin endpoint
   `PUT /api/newsletter/settings/smtp-password` (permission `newsletter.manage`, tenant-bound router
   per CLAUDE.md, CSRF as the host's other admin JSON writes) that encrypts with `enc:v1:` and
   persists. Test the stored row value is ciphertext. A plaintext value found at read time is
   still accepted with a warning (an operator wrote the DB directly).
6. **Reconcile sees trash.** Records' `iter_subscribers` gains `include_trashed: bool = False`,
   accepted only with `status="unsubscribed"` (ValueError otherwise); the reconcile passes it.
   Records test plus a newsletter test: lost event -> trash -> reconcile -> purge -> still suppressed.
7. **`task_config.py` declares `QUEUES = {QUEUE_DEFAULT}`** (the newsletter queue), with a test that
   a worker scoped to `newsletter` imports the newsletter tasks.
