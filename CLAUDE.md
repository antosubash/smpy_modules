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
(`simple_module_hosting==0.0.44`). Never give a published module an `==` pin —
it becomes uninstallable in any host running a newer framework build.
`scripts/check_rules.py` (in `make lint` and CI) rejects one, and also any
requirement on another module of this repo (news' `pagebuilder` extra) without
a `>=` floor and a `# floor: <reason>` comment saying which change that version
first shipped. It never compares the floor with the lockstep version, so raise
the floor and its comment together when a module starts using something newer.
`scripts/check_sibling_contracts.py` (also in `make lint` and CI) catches the
contract case: every `<sibling>.contracts` module and name a module imports
(an `import_module("…contracts…")` string included) must exist at tag
`v<floor>`, or in the working tree for a floor that is the next patch, minor
or major after the newest tag (the release being prepared; any other floor
without a tag is an error). It needs the tags (`git fetch --tags`).

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
0.0.43's `a738c2e4f601` and `e731a1b2c3d4` and 0.0.44's `e805a1b2c3d4`,
`c5d8e2f1a903` and `f6c2d4e8b109` follow `c4e9b2a7d613`. Upstream's
`b8d4f2a6c901` (audit_log) and `c9d2e4f6a810` (oidc) are not ported: neither
module is installed here, so their tables do not exist. `e731a1b2c3d4` refuses
to run while two accounts' emails differ only by letter case, and prints them masked
(`a***@host`) with the query that lists them.
`host/migrations/env.py` ignores the false change autogenerate reports on SQLite
for a mixed column-and-expression index (it reflects `created_at DESC` as a plain
column, so `tenant_browse` would be dropped and recreated on every run). One on
other columns is still reported; a missing one only by the Postgres check, because
Alembic skips expression indexes on SQLite.
**Since 0.0.44 most framework modules follow the module layout**, and the old
flat paths (`tenants.resolver`, `settings.service`, …) warn and go in 0.0.46
(a few in 0.1.0). Import the new path, and raise that dependency's floor to the
release that first shipped it; `host/tests/test_host_boots.py` fails on any
import of a path the installed framework marks `deprecated_module`.
**Since 0.0.43 the production CSP is nonce-based** (`'nonce-…' 'strict-dynamic'`,
no `unsafe-inline` or `unsafe-eval`): an executable `<script>` in a template needs
`nonce="{{ request.state.csp_nonce }}"`, and `eval`/`new Function` no longer run.
An Inertia GET without `X-Inertia-Version` gets a 409, so a test client sends it;
the adapter strips `ETag` from every Inertia payload and marks it `private,
no-store`; and the page JSON lives only in `<script data-page="app">`.
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

**Every pagebuilder, news, records, images and newsletter entry point binds a tenant (#38, #112).**
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
own copy, `news.core.tenancy`, and its scheduler ticks per tenant the same way;
records' is `sm_records.core.tenancy` (its 403 is the `{"detail","code"}` envelope,
code `tenant_required`), images' `sm_images.core.tenancy` is a copy of it, and newsletter's
`sm_newsletter.core.tenancy` is a copy of images'; images'
Celery tasks never run unscoped — `images.reconcile` and `images.janitor`
enumerate tenants in one narrow `all_tenants()` read and do each tenant's work
under `tenant_context`, and newsletter's hourly reconcile does the same, enumerating
tenants through records' `subscription_list_tenants` (worker-only); billing reads the same `request.state.tenant_id`
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

**Newsletter content and test sends.** Email HTML is produced only by
`sm_newsletter.content.render`. Rich text is re-serialised from an allow-list at
save and again at render. Card and media lookups go through
`news.contracts.articles` and `pagebuilder.contracts.cards` only
(`content/integrations/` is the one package that imports them, guarded). A
settings write that changes the SMTP host, port, security or username clears the
stored password. Campaign writes are guarded by an integer `revision`
(`expected_revision`, 409 `stale`), and every campaign request re-checks the
caller's list access (404 for an unreadable list). A test send takes the
install-wide dispatch lock (`sending/lock.py`: Postgres advisory lock, SQLite
lease row) and counts against the rolling budget through
`newsletter_send_attempt`; admission is all-or-nothing and writes no row on
refusal. A test goes only to vouched-for addresses (#348,
`campaigns/test_recipients.py`): the caller's own email, active accounts of the
bound tenant (framework `UserDirectory` by exact address, a verified email
where the directory reports one, then `tenant_member_ids` on a multi-tenant
host; fail closed without either) and the
SYSTEM setting `test_send_extra_recipients`. Any other is `recipient_not_allowed`,
and one with a `complaint` or `unsubscribed` suppression in the tenant is
`suppressed` (suppression hashes and newsletter's own address comparisons use
`normalise_email`: local part NFC + `lower()`, domain as email-validator
normalises it; reads also try the legacy `strip().lower()` key; what is handed
to or searched in records, the Mailchimp hand-off and the lift screen's
records search, uses records' `records_form`); both are decided before the
lock, write no attempt row and use no budget. A result is `outcome` plus a stable `code` (`smtp_<reply>`,
`dispatch_busy`), never the relay's reply text (ledger and log only). Content
links use the campaign tenant's public origin, while the unsubscribe and logo
routes use `public_base_url`; the email logo is
`/newsletter/brand/logo` (the SYSTEM-scope branding logo). Docs:
`modules/newsletter/docs/content.md` and `sending.md` (Test sends).

**Newsletter mirrors records' unsubscribes into `newsletter_suppression`.** The
`SubscriptionChanged` handler writes them, and an hourly reconcile walks records'
unsubscribed subscribers, trash included, and only adds rows. Suppressions are
tenant-wide: an opt-out on any list suppresses every list in the tenant. Only a
double-opt-in confirmation (records' confirm link, the one `pending → confirmed`
event) clears anything: that list's opt-out and the bounce/import rows created at
or before it, never `complaint`, never another list's opt-out. A single-opt-in
signup (`None → confirmed`, anyone can type the address) clears nothing. An admin
lift (`POST /api/newsletter/suppressions/{id}/lift`) is the only other way a
row is deleted. It needs `newsletter.manage`, the typed address (hash match) and a
note, and writes `newsletter_suppression_lift`; it is never allowed for a
`complaint`. An `unsubscribed` row lifts only while records shows that address
confirmed on that list after the opt-out. That check and the delete run under
records' lock (`lock_confirmation`: type lock, then row), which every unsubscribe
also takes (`opt_in.leave` → `transition(lock=True)` → `lock_record`). A new records
path that unsubscribes must take it too. A campaign's audience is resolved when it
is scheduled and stored on the render snapshot; freeze evaluates that snapshot,
never the live segment.

**The Mailchimp import never clears and never confirms a pending signup.**
- Records' `contracts.newsletter_import.import_subscribers` creates `confirmed` (or
  `unsubscribed`) records directly through `system=`. It never moves `pending` or
  `unsubscribed` to `confirmed`, unsubscribes a confirmed record only under PR 6's row lock,
  and publishes no events (`events.muted`). It holds records' type lock for the whole batch.
- Newsletter then writes `unsubscribed` (list) and `imported_cleaned` suppressions with
  `refresh=False`, in the same transaction, and never calls `clear_for_confirmation`.
- A subscribed address newsletter already suppresses, or records holds `unsubscribed` on any
  list of the tenant (`opted_out_anywhere`), is not created. Both are read after
  `lock_import_batch`: records' per-address opt-out locks (`pg_advisory_xact_lock`, ascending
  key, which every `opt_in.leave` takes first too), then the type lock. Order: address locks
  → type → row → newsletter rows. On SQLite the type-lock `UPDATE` comes before the read.
- Uploads are staged in `newsletter_import_row` (addresses, deleted when the import ends or
  after 24 h) and applied by `newsletter.run_import` in leased 45 s slices under
  `tenant_scope`. Eager hosts run it inline.
- The import publishes no `SubscriptionChanged`, so no other consumer of records' events sees
  imported changes.
- `POST /api/newsletter/lists` creates a records list type with only `newsletter.manage`.
- `POST /api/newsletter/outbox/dispatch` runs a dispatcher tick in-process only with the
  console transport, under Celery eager, with `SM_ENVIRONMENT` `development` or `testing`
  (it defaults to development, so the other two conditions carry the weight); the e2e spec
  depends on it.
- Docs: `modules/newsletter/docs/import.md`.

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
`subject_mode = user` (restart-only, refused at boot on a multi-tenant host) makes a signed-in user the billing subject instead of a tenant; see `modules/billing/docs/subjects.md`.
In `user` mode images bills `user:<collection owner>` (#284). The subject is
recorded per hold (`images_billing_op.subject`, `images_image.storage_subject`;
`NULL` = the row's tenant), and settle, repair and growth replay it and never
re-derive it. A new images billing call takes its subject from the op or image,
or from `sm_images.core.billing.subject`.
Two more billing invariants: webhook payloads are never trusted for state (every
event re-fetches the subscription through `sync.resync`/`apply_snapshot`, the
one place provider state becomes local state), and response models
(`PlanOut`) must not inherit input bounds — a stored row that predates a bound
would 500 every screen listing plans. Its docs are in `modules/billing/docs/`.

**`pagebuilder`, `news`, `billing`, `ai`, `images`, `newsletter` and `records` read no environment variables for their settings.** The exceptions are the stored-secret crypto's: ai, billing, newsletter and records read `SM_SECRET_KEY_PREVIOUS` (below), and ai and newsletter also fall back to `SM_SECRET_KEY`. Their settings are
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
Newsletter's `smtp_password` is stored `enc:v2:` under `SM_SECRET_KEY` (0.0.15's `enc:v1:` is still
read until 0.1.0) and written only
through `PUT /api/newsletter/settings/smtp-password` (needs `newsletter.manage` and
`settings.edit`; on the `smtp` transport workers **refuse** a non-empty SMTP password stored without an `enc:` prefix
(as `scripts/set_setting.py` would store it; the check is `crypto.is_encrypted`, never one version's prefix), and the dispatcher does not run until it is re-saved
through that endpoint, so always use the endpoint); the generic Settings screen
refuses newsletter writes (`manage_url`).
These settings are SYSTEM-scope: ai has one provider configuration and one
API key per slot for the whole deployment, shared by every tenant. ai reads
three things from the environment (`SM_SECRET_KEY_PREVIOUS`, below, is the third), all only as the framework's
`BootstrapSettings` locates `.env` (`SM_PROJECT_ROOT`, else the walk up to the
project root) — never a cwd-relative file (#124): `SM_SECRET_KEY`, for its key
encryption, and `SM_DATABASE_URL`, only when `sm_ai.contracts.consume_requests`
is called without a `session_factory` while billing is installed (it then opens
its own NullPool engine on the host database, `metering._own_factory`). Images
always passes its factory, so that fallback is for other callers.
**Stored secrets rotate with `SM_SECRET_KEY_PREVIOUS` (#351).** ai, billing, newsletter and records
each keep a copy of one `core/crypto.py` (parity family "stored-secret crypto",
`scripts/tests/parity_crypto.py`; byte vectors in `scripts/tests/test_secret_crypto_formats.py`):
writes are `enc:v2:` (HKDF-SHA256 of the secret, info `<package>:settings`), `enc:v1:` is read until
0.1.0, any other `enc:` is unreadable (never plaintext), and every copy decrypts with
`SM_SECRET_KEY_PREVIOUS` too — one key or a JSON list, from the process env else the located `.env`.
That variable is the one environment read billing and records make. Change the four copies
together; `scripts/reencrypt_secrets.py` lists their fields in `reencrypt_support.TARGETS`. Signed
things (sessions, newsletter and records links, form tokens, image tickets) are not covered:
`docs/secret-key-rotation.md`.
**Records' `public_submissions_captcha_secret` is never stored in the clear (#350).** It is a
`SealedSecret` (`str | None` with an encrypting serializer), so the framework treats it as a json
field and the Settings screen stores its validated dump — `enc:v2:` — and `scripts/set_setting.py`
stores a json field's dump the same way; records' secret provider is installed in
`register_settings` (`core/boot.register_settings`) for the headless scripts. Startup seals a legacy
plaintext row (compare-and-set); `captcha.verify` decrypts per check and fails closed (503). A new
records secret field uses `SealedSecret` too; never a plain `str`. Images' workers never build the app, so they read
the same class with `background_tasks.settings_for(ImagesSettings, "sm_images")`
(DB-backed, cached about 30 s).

**Newsletter campaigns are sent only by the `newsletter.dispatch` beat.** It holds the
install-wide `dispatch_lock` per slice (at most 10 counted sends), and each recipient's attempt
row is committed before its SMTP call; the worker never renders, it personalises the render
snapshot written when the campaign was scheduled. `/newsletter/u/{token}` is the **second
documented exception** to "the public surface binds the resolved tenant", after records' signed
form token: it binds the tenant from the HMAC-verified token, answers an unknown, foreign or
forged token exactly as it answers a real one (so it cannot probe which tokens exist), and
carries no CSRF on purpose (RFC 8058). `/newsletter/o/` and `/newsletter/c/` follow the same rule
(tenant from the verified token, purpose-bound MACs, one answer for forged tokens); only a
*host-derived* tenant (`subdomain`/`fixed`) can refuse a token, never a session or header one
(`public_tenant.host_tenant`). The click route redirects only to the campaign's own stored
`newsletter_link` URL, and tracking stores no IP or user agent. Only an RCPT-stage `5.1.x`
bounces; any other 5xx pauses the campaign. Docs: `modules/newsletter/docs/sending.md`,
`tracking.md` and `operations.md`.

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
New code in any module follows it. Every module follows it; structural changes keep the same moves-only
review boundary.

**The paths 0.0.14 moved stay importable until 0.0.17 (#319).** Each moved
package's `core/moved_paths.py` hook, driven by `core/moved_paths.json`, aliases
the old Python paths with a `DeprecationWarning`. Generated re-export stubs sit
at the old TS paths (the `components/`, `hooks/` and `utils/` folders that hold only
stubs). Never edit or import them: `scripts/moved_paths.py --check` (`make lint`,
CI) fails on a stub that drifts from its table and on any repo import of an old
path. `host/tests/test_moved_paths_tables.py` fails once the version reaches
`remove_in`; then delete the stubs, both `core/moved_paths.*` files, the
`install(__name__)` lines, the `__getattr__`/`__all__` lines (ai's `metering`,
billing's `plans`) and the `__path__` lines (records' `index` and `seed`),
`scripts/moved_paths*` with its test and the `--check` lines in the Makefile and
`ci.yml`, `host/tests/test_moved_paths*.py` and `moved_paths_probe.py`, and the
stub filter in the `test_layout.py` of ai, billing and news.
A later move needs aliases the same way.

**300-line cap** on every `.py` / `.ts` / `.tsx`, enforced by
`scripts/check_file_size.py`. Nothing under `modules/` is exempt. The check
also lists files at 280+ lines as a WARNING: when you touch one, split it by
responsibility rather than trimming comments until it fits (#133). A mixin
split out of a service declares what it needs from the composing class as a
`Protocol` (`pagebuilder/content/service/_host.py`, `news/content/_host.py`) — add a
member there before a mixin uses it; the `test_*_host.py` tests enforce it.

**Pyright checks only its include list (#338).** `make lint` and CI run
basedpyright (basic mode) over `[tool.pyright] include` in the root
`pyproject.toml`: every `contracts/` package and the cross-module code that
calls one. Widen it module by module. In those files a SQLModel column in a
query goes through `sqlmodel.col()`, and a suppression is
`# pyright: ignore[rule]` with its reason. Ruff's `S` (bandit) rules are on
(except `S101`: an `assert` only narrows a type after a check); tests and
`scripts/` have per-file ignores, production code takes a line-level
`# noqa: Sxxx - <reason>`.

**Every e2e spec file stands alone.** CI shards the suite by file
(`--shard=i/3`, one host and database per shard, #119), so a spec cannot rely
on data or settings another file created. Seed what you need in the file
itself; suite-wide settings belong in `tests/e2e/start-test-server.sh`. Locally,
`make e2e-parallel` runs the same bundle suite in three shards on one machine
(`scripts/e2e_shards.mjs`: one template database copied per shard, each with its
own host, port and upload directories); `make e2e-bundle` stays serial. The
`E2E (Playwright)` job merges the shards' reports and is the one status that
covers all of them. `newsletter.spec.ts` is opt-in with `E2E_NEWSLETTER=1`. It runs only in
its own CI job, `E2E (newsletter)`, against a non-bundle host with
`SM_ENVIRONMENT=development` (framework 0.0.42 serves `testing` pages from the Vite dev
server under the strict production CSP, so the console is blank), because its dispatch hook
is absent in production. The bundle shards ignore it. Run it locally with
`E2E_NEWSLETTER=1 npx playwright test`.

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

Redis and Celery are used by the **images** and **newsletter** modules (framework
`background_tasks`, host pinned `==0.0.44`): `SM_REDIS_URL` points at dev-services'
Redis, and `make worker` / `worker-imports` / `worker-heavy` / `worker-gpu` /
`beat` run `host/worker.py` (`build_runner_celery`) with one queue set each.
`make dev` starts none of them. With no worker, set
`SM_BG_TASKS_TASK_ALWAYS_EAGER=true` (`.env.example`; the e2e server exports it,
plus `..._TASK_EAGER_PROPAGATES=true`) and tasks run inline. CI installs
`tippecanoe` with apt in the Python-tests and Postgres jobs. **The images
`[anonymize]` extra (onnxruntime) is never installed by default.** `make install`,
the Python-tests, Python lint, repo-checks, e2e (`.github/actions/e2e-setup`) and `release`
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

- **UI i18n — done in every module, in English and German.** All seven ship
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
  key the JSON does not define. See `modules/news/news/ui/utils/i18n.ts` — about
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
  Billing's `subject_mode = "user"` (#274) has its own opt-in spec,
  `billing-user`, run with `E2E_BILLING_USER=1` in the CI job
  `E2E (billing per user)`; `start-test-server.sh` sets the mode before boot.
  `newsletter.spec.ts` is opt-in with `E2E_NEWSLETTER=1` and runs only in the CI job
  `E2E (newsletter)`, on a non-bundle host with `SM_ENVIRONMENT=development` (`testing`
  blanks the console under framework 0.0.42's CSP); its dispatch hook is absent in
  production, and the bundle shards ignore it.
