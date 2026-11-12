# Changelog

One version covers every package in this repo (releases are lockstep). Entries
name the module they affect.

## 0.0.16 (unreleased)

### Security

- **pagebuilder's admin reads need a pagebuilder permission** (#346). Signing in
  used to be enough to read every draft, its revision history, the unpublished
  site layout and the media library, over the API and on the screens (the
  draft preview included), which on a host with self-registration or customer
  accounts meant every customer. Now a signed-in user needs one of
  `pagebuilder.edit`, `pagebuilder.publish` or `pagebuilder.approve`, and gets
  `403 Permission required: pagebuilder.edit` otherwise. Pages, Site layout and
  Media library leave the sidebar on the same condition. A signed-out request
  answers as before. news' admin search shows its Pages and Media sections only
  to such a reader too. **Upgrading:** give every account that edits the site
  one of the pagebuilder roles (see "Roles" in
  `modules/pagebuilder/docs/operations.md`); no migration is needed.
- **pagebuilder refuses an unsafe block link on save** (#354). A page draft or
  the site layout whose blocks carry a link outside `http`, `https`, `mailto`,
  `tel` or a relative address (`javascript:`, `data:`, `vbscript:`, …), in any
  `href`/`…Href` prop or a Markdown link in text, is a 422 naming the block and
  the field. An `Iframe` or `Video` block's `src` may only be `http(s)` or
  relative. An uploaded bundle is refused the same way. Every block now renders
  its links through one helper, `safeHref` (frames through `safeFrameSrc`), so
  a value stored earlier shows as `#` (a frame as the empty block). React and
  the public CSP already kept such a link from running; this keeps it out of
  the data other consumers read. A leading space no longer hides a scheme from
  `isSafeHref`.
- **pagebuilder strips camera metadata from uploads** (#356). A JPEG, PNG or
  WebP original is stored without EXIF (GPS, device, serial, capture time), XMP,
  IPTC or comments, its ICC profile kept; `size_bytes` is the cleaned file's. A
  JPEG is re-saved with its own quantisation tables and its EXIF orientation
  applied; a multi-picture JPEG (MPO, as phones save photos) keeps only its
  primary picture, as a plain JPEG. A JPEG's segments are all checked, between
  progressive scans too, and a JFIF or JFXX thumbnail counts as metadata.
  Whatever follows a JPEG's end (a motion photo's video and trailer) goes too: a
  JPEG with nothing else to remove is cut losslessly at its true end, found by
  walking its markers, or re-saved when they do not lead to one (a truncated
  file from a camera or scanner). A PNG or WebP is not re-encoded: its metadata
  chunks are dropped and the compressed picture copied byte for byte, so a
  16-bit PNG keeps its depth and a lossy WebP loses no quality. Only a still
  WebP or 8-bit PNG with an EXIF orientation is turned and re-saved. Animated
  PNG (APNG) and WebP are cleaned the same way, every frame kept and none
  turned. GIF is stored untouched, and so is a file with nothing to remove. It
  fails closed: a file that cannot be read, parsed or re-saved, or an animation
  with a frame that does not decode, is refused with `415`
  `image_metadata_not_removed` (the console says why), never stored with its
  metadata; an animation whose frames total over ten times the pixel limit is a
  `413`. The new setting `media_strip_metadata` (on by default) turns it off.
  Not retroactive: files already in the library keep their metadata. The media
  and snapshot settings moved to `pagebuilder.core.settings_media`
  (`PagebuilderSettings` inherits them, so nothing changes for a caller), which
  lists them first on the Settings screen.
- **Stored credentials survive a `SM_SECRET_KEY` rotation** (#351, ai, billing,
  newsletter, records). Each module now encrypts under its own key (HKDF-SHA256
  of the secret, info `<package>:settings`) and writes `enc:v2:…`; every module
  also decrypts with the keys in the new `SM_SECRET_KEY_PREVIOUS` (one key or a
  JSON list, from the environment or `.env`; read only for a value the current
  key does not open, so a malformed value — an error naming the variable, never
  its value — never breaks what the current key opens), and the new
  `scripts/reencrypt_secrets.py` re-encrypts every stored secret under the
  current key, all or nothing, never printing a value. A stored value with an
  unknown `enc:` version is refused instead of being used as plaintext. The
  unreadable-key errors name `SM_SECRET_KEY_PREVIOUS`. Signed things (sessions,
  newsletter unsubscribe/open/click links, records' form tokens and confirmation
  links, images' upload tickets) are not covered. Procedure:
  `docs/secret-key-rotation.md`.
- **records stores the CAPTCHA secret encrypted** (#350).
  `public_submissions_captcha_secret` was kept in the settings table in the
  clear; it is now stored `enc:v2:…` whichever way it is saved (the Settings
  screen and `scripts/set_setting.py` store the encrypted value, never the text
  typed), and decrypted per submission. A secret that no key opens refuses
  submissions with `503 captcha_unavailable`, logged by field name only. The
  framework's `smpy settings import-from-env` still stores what it imports as
  written; a CAPTCHA secret imported that way is encrypted at the next start. The
  field is typed `str | None` (a JSON string for `set_setting.py`:
  `'"<secret>"'`). `scripts/set_setting.py` now stores any JSON field as its
  type dumps it, as the Settings screen does, and no longer echoes a value the
  screen would mask.
- **ai checks where a base URL points before sending the key there** (#347).
  `chat_base_url` and `embedding_base_url` must be `http(s)`, and their host
  must resolve only to public addresses: loopback, private, link-local (the
  cloud metadata address included), CGNAT, multicast, reserved and mapped or
  tunnelled forms of those are refused on save (a `422` naming the setting to
  turn on) and again at every request. The SDK clients for OpenAI,
  `openai_compatible`, Anthropic and Google all get an HTTP client pinned to the
  validated address (the name stays the `Host` and TLS name), so a DNS answer
  that changes after the check cannot redirect the key. A local endpoint such
  as Ollama or an in-network gateway needs the new SYSTEM setting
  `allow_private_base_url`, off by default, which only a holder of
  `settings.edit` can change (a **Network** card on the AI page). `POST
  /api/ai/test` and `/api/ai/models` now answer a stable `code`
  (`base_url_refused`, `unreachable`, `connection_refused`, `timeout`,
  `unauthorised`, `http_error`, …) with a fixed message, translated in the
  console, instead of the provider's error text, which is logged server-side
  only. ai now depends on `httpx2` directly (already installed through the
  SDKs). Details: "Base URLs and the network" in `modules/ai/docs/operations.md`.
- **newsletter test sends go only to vouched-for addresses** (#348). A test used
  to go to any five addresses, suppressed ones included, and returned the
  relay's reply text. Now each recipient must be the caller's own address, an
  active account of the campaign's organisation (the framework's user
  directory, plus membership of the bound tenant on a multi-tenant host), or one
  of the new SYSTEM setting `test_send_extra_recipients` (up to 20, for a shared
  review inbox; on the Settings page); any other answers
  `recipient_not_allowed`. An address with a `complaint` or `unsubscribed`
  suppression in the tenant answers `suppressed`. Neither is sent, writes an
  attempt row or uses budget. A result is now `{recipient, outcome, code}` with
  a stable `code` (`smtp_250`, `smtp_550`, `dispatch_busy`); `detail` is gone
  from the response and kept in the attempt ledger and the server log. The
  test-send dialog names each refusal. Suppression keys and address
  comparisons now use one canonical form everywhere: the local part NFC and lower-cased, the domain as
  email-validator normalises it (IDNA 2008, so `xn--fa-hia.de` is `faß.de`). A
  suppression written under one spelling of a domain covers every spelling, a
  fullwidth or ligature local part is a different mailbox (and is not vouched
  for), and ASCII addresses keep their keys. The table stores only the hash, so
  every lookup also tries the old `strip().lower()` key of the spelling it has,
  until newsletter's first published release, when that legacy lookup can go;
  newsletter is not yet published, so no migration or other upgrade step
  applies. Details:
  `modules/newsletter/docs/sending.md`.
- **records' anonymous listing has its own, smaller query bounds** (#349). A
  public listing or stats request takes at most 3 `filter` terms, of which at
  most one may be `contains` (an unindexed `ILIKE '%term%'` scan), and answers
  `400` with `code` `too_many_filters` or `too_many_contains` beyond that; one
  request could ask for twenty substring scans before. On Postgres the query
  runs under a 5 s `statement_timeout` (`SET LOCAL`), and a cancelled query is
  a `503` with `code` `query_timeout` instead of a 500. The admin API keeps
  `max_filter_terms`, and the records list and stats blocks send one term each.
  Details: "Public read API" in `modules/records/docs/api-reference.md`.
- **images' share picker no longer lists the user directory** (#357).
  `GET /api/images/collections/{id}/share-candidates` answers `[]` for a `q`
  shorter than three characters (an empty one included) without searching, and
  is rate-limited to 60 requests a minute per user. On a single-tenant host an
  account that could create a collection could page through every user's name
  and address with an empty or one-letter query. The share dialog says "Type at
  least 3 characters to search." until then. Details: "Sharing" in
  `modules/images/docs/access.md`.
- **Absolute URLs built from the client's `Host` header are caught** (#355).
  pagebuilder and news build canonical, `og:url`, `hreflang`, feed and sitemap
  links from the request when `public_base_url` is blank; billing did the same
  for Stripe's Checkout and portal return URLs when `return_base_url` was. Now:
  while `public_base_url` is blank, every such pagebuilder and news response
  (pages and their 304s, archives, the feed, the sitemaps, the generated
  `robots.txt`) adds `Host` to `Vary`, so a shared cache cannot hand one host's
  links to another; and a single-tenant host outside `development`/`testing`
  logs a startup warning naming the setting. A multi-tenant host, where blank
  is right, gets the `Vary` and no warning. On a single-tenant host the host's
  own `public_base_url` now stands in for a blank module setting in all three
  modules. billing refuses Checkout and the portal with 409
  `return_base_url_missing` when neither is set on a single-tenant host outside
  `development`/`testing`; it is checked only once Stripe would need the URLs,
  so `checkout_unavailable`, `plan_not_found` and `no_customer` still answer
  first, and a multi-tenant host keeps the request's origin. The billing screens
  say so; the Connection page says the field is required in production.
  **Upgrading:** on a single-tenant production host, set the host's
  `public_base_url` (or each module's own setting). Details:
  the `public_base_url` / `return_base_url` rows in each module's
  `docs/operations.md`.
- **pagebuilder and news refuse a read with no tenant bound** (#335). They now
  install the fail-closed ORM guard records, images and newsletter already had:
  an ORM statement or flush on one of their tables with nothing bound raises
  `TenantUnbound` instead of returning every tenant's rows, so a future entry
  point that forgets to bind fails loudly. The schedulers' tenant scan and
  pagebuilder's boot-time media scan are tagged as deliberate cross-tenant
  reads, and `pagebuilder.contracts.search` now binds the tenant its caller
  names (a caller bound to another tenant gets `TenantIsolationError`), as the
  cards contract already did. The five guard copies are parity-checked. Billing
  has no `MultiTenantMixin` table, so it has no guard. No migration is needed.

### Changed

- **news, pagebuilder, analytics and records settings use the framework's
  `DbBackedSettings`** (#345), as ai, billing, images and newsletter already
  did, instead of each carrying its own `settings_customise_sources` (records'
  `StoredSourcesOnly` mixin is gone). Behaviour is unchanged: the same fields,
  defaults and validators, no environment, `.env` or secrets-file source. No
  dependency floor moves; `DbBackedSettings` has shipped since framework 0.0.33.
- **pagebuilder has a TypeScript entry point** (#337).
  `@simple-module-py/pagebuilder` (`pagebuilder/index.ts`, the package's
  `main`) exports what other modules use to contribute blocks:
  `registerPuckBlocks`, `registeredBlocks`, `lazyBlock`, `StatsView`,
  `ArticleCardsGrid`, `Section`, `createImageField`, `mediaLibraryAdapter`,
  `isSafeHref` and `safeHref`. news, records and images import only these now,
  and `scripts/check_ts_imports.py` (`make lint`, CI) refuses a deep import
  into another module's package (`@simple-module-py/<module>/<file>`, or a
  relative path into `modules/<other>/`). Nothing breaks: deep paths into
  pagebuilder, the 0.0.14 moved-path stubs included, still resolve until
  0.0.17, when pagebuilder gets an `exports` map. A host or module that
  imports pagebuilder's files by path should import from the package root
  instead; the widget stylesheet will then be
  `@simple-module-py/pagebuilder/widgets-base.css`.
- **A module reaches a sibling's Python only through its `contracts`** (#336).
  `scripts/check_sibling_contracts.py` (`make lint`, CI) now also fails on any
  import of `<sibling>.<anything but contracts>` in a module's non-test code:
  plain and from-imports, and `import_module`/`find_spec` strings. Its
  allow-list is empty. The reads that broke the rule go through contracts now:
  - ai's `RequiresAiRequest` imports `sm_billing.contracts.RequiresQuota`
    (new), and ai has a `billing` extra (`simple_module_billing>=0.0.16`).
    **Upgrade billing with ai:** ai 0.0.16 next to billing 0.0.15 refuses to
    start (`RuntimeError` naming the fix) rather than serve AI requests
    unmetered. Without billing nothing changes.
  - news reads its content languages through the new
    `pagebuilder.contracts.site` (`content_locales(app)`, `supported()`,
    `default()`, `resolve()`, …), not `pagebuilder.core.locales` and
    `app.state.pagebuilder`. Its `pagebuilder` extra's floor is now 0.0.16.
  - records' CAPTCHA startup check reads `site.public_csp(app)`. Its
    `pagebuilder` extra's floor is now 0.0.16.
  - newsletter asks `news.contracts.articles.mounted(app)` and
    `pagebuilder.contracts.cards.mounted(app)` (new), not `app.state`.
  - records' newsletter contract writes (`unsubscribe`, `set_tags`,
    `create_list`, `add_tag_choices`, `import_subscribers`) take the caller's
    `app` (`None` in a worker), not a `settings: RecordsSettings` argument.
    Records reads its own settings from that app, or with `settings_for` in a
    worker. `newsletter_import` no longer exports `RecordsSettings`. These
    contracts first ship in 0.0.16, so no released caller breaks.
- **Every module's console uses the framework's CSRF token** (#342). The
  token is now the framework's `csrfToken` shared prop, which every signed-in
  page carries, read through `currentCsrfToken` from `@simple-module-py/ui`.
  ai, images, news, newsletter, pagebuilder and records no longer share their
  own `csrf_token` prop. Their `share_csrf_token` hooks are gone, and so are images'
  and newsletter's `web/endpoints/csrf.py`. analytics drops its `csrf_token`
  page prop and its `ui/utils/csrf.ts`. Each remaining `ui/utils/csrf.ts` only
  adds the header to the module's own `fetch` (and pagebuilder's upload XHR)
  and translates the framework's 403. A token no longer outlives a page that
  carries none (a sign-out). billing's `api()` is built on `apiFetch`, and
  keeps passing its pages' own `csrf_token`. **Scripted clients** that read
  `csrf_token` from an ai, images, news, newsletter, pagebuilder, records or
  analytics page should read `csrfToken` instead. The `web/csrf.py` of ai, news
  and records stays only as the target of the deprecated `<module>.csrf` alias
  until 0.0.17 and shares nothing. Floors: `simple_module_hosting>=0.0.38` for
  ai, news and pagebuilder, and `@simple-module-py/ui>=0.0.38` as every module's
  peer. The four `ConfirmDialog` copies stay: `ConfirmActionDialog` has no
  trigger or async `onConfirm`, so it cannot show the refusal in the dialog.
- **records' services are grouped by feature** (#343). The private helpers of
  `sm_records.records.services` moved, unchanged, into one subpackage per
  feature: `imports/` (`_import_*`), `delete/` (`_lifecycle`, `_delete_locks`,
  `_delete_plan`, `_empty_trash`, `_forget_deliveries`), `expansion/`
  (`_expand_*`), `referrers/` (`_referrer*`), `translations/`
  (`_translation*`), `type_writes/` (`_type_*`), `claims/` (`_claims`,
  `_unique_claims`, `_uuids`), `reindex/` (`_reindex_markers`, `_titles`) and
  `schema_changes/` (`_dry_run`, `_duplicates`, `_invalid`, `_orphaned`,
  `_pending`, `_preview`, `_rollback`). The public services (`records`,
  `types`, `errors`, `import_`, `expand`, `public_stats`, …) and the helpers
  several features share (`_common`, `_payload`, `_lock`, …) stay in
  `services/`. Nothing outside records imported a moved module, so the new
  paths get no alias; the 0.0.13 aliases (`sm_records.services._claims`, …)
  now point at the new locations and still go in 0.0.17.

### Deprecated

- **`enc:v1:` stored secrets** (ai, billing, newsletter). Still read, with one
  warning per field, until **0.1.0**. Run `scripts/reencrypt_secrets.py`, or
  re-save each secret, to rewrite them as `enc:v2:`.

### Upgrading

- Stored secrets: nothing is required. Existing `enc:v1:` values keep working, and records
  encrypts a plaintext CAPTCHA secret in place at the first startup (a warning
  says so). Downgrading to 0.0.15 after a secret was saved again (or
  re-encrypted) leaves it unreadable there (`enc:v2:`); re-enter it after a
  downgrade. records now depends on `cryptography>=42`.
- **ai: a private base URL needs `allow_private_base_url`** (#347). A slot
  pointing at a local or in-network endpoint (Ollama, vLLM on
  `http://vllm:8000/v1`, `http://127.0.0.1:…`) stops working on upgrade: calls
  fail and **Test connection** says the base URL was refused. Turn on **Allow
  private base URLs** on the AI page (needs `settings.edit`), or run
  `python scripts/set_setting.py sm_ai allow_private_base_url true`. A client of
  the probe routes that read `error` should read `code`.

### Fixed

- **billing's last four bare `commit()` calls are `finalize_session`** (#340):
  the webhook claim and finish, the seat-quantity push and the default-plan
  seed. None queued `on_commit` work, so nothing changed today, but a later
  `set_status` inside one would have suspended a tenant while every member's
  cached view said active. billing's `test_commit_sites.py` allowed those four;
  its allow-list is now empty, so any `.commit()` in `sm_billing` fails it. The
  seat push also calls the provider
  between two short transactions instead of inside an open one.

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
- newsletter's operations guide says the web process and its workers must
  reach Postgres directly or through a session-mode pooler (#344). The dispatch
  lock is a session-level advisory lock, which PgBouncer in transaction mode
  breaks: sends time out on the lock (`dispatch_busy`), or two senders overrun
  the budget.
- The repo has a `SECURITY.md` (#358): report a vulnerability privately through
  GitHub, not in a public issue.
- **CI tests the Python and Node the image ships** (#359). The Dockerfile's
  runtime stage runs Python 3.14, but every test job ran 3.12, so the
  interpreter the demo image runs had never executed the suite and nothing
  backed the modules' `requires-python = ">=3.12"` above the floor. The
  Python-tests job is now a matrix of 3.12 and 3.14 (its checks are
  `Python tests (pytest, 3.12)` and `Python tests (pytest, 3.14)`), and the
  Docker job loads the image it builds, starts it in production mode and waits
  for `/health/live` (`Docker image (build + boot)`), printing the container's
  logs. CI and the release workflow run Node 26, the `ui` stage's major, instead
  of 24.
- **Every module's suite runs on Postgres, ai's included** (#360). The Postgres
  job named each module and its `ci_<module>` database by hand, so ai never ran
  there and a new module would have been skipped until someone edited the
  workflow. `scripts/pytest_modules_pg.sh` now walks `modules/*/` as
  `pytest_modules.sh` does, creates each module's database and reports every
  module even after one fails (one step, `Run pytest (each module, Postgres)`).
- **The nightly framework-latest run can fail** (#360). It was
  `continue-on-error`, so a framework release in the modules' range that broke a
  module showed up only to someone who opened the run; its nightly runs had been
  green.
- **ci.yml pins its actions by commit SHA** (#360), with the release in a
  comment, as `release.yml` and the e2e setup action already did, and so do
  `framework-latest.yml` and `images-models.yml`: a tag can be moved by whoever
  controls the action's repository. ci.yml also states `permissions: contents:
  read` instead of relying on the repository's default token setting.
- **A Python type checker runs in `make lint` and CI** (#338): basedpyright in
  pyright's basic mode over every `contracts/` package and the code in other
  modules that calls one (the `[tool.pyright]` include list in the root
  `pyproject.toml`, to be widened module by module). What it found is fixed
  without changing behaviour: SQLModel column expressions in those files go
  through `col()`, the bundle protocol's `count_label_keys` is a
  `ClassVar[Mapping]` (news' section did not match it), images' `user_subject`
  returns `None` for a missing owner before calling billing instead of relying
  on `ValueError` from `str(None)`, and newsletter's import upload error reads
  `detail` only where it exists. Ruff's flake8-bandit rules (`S`, except
  `S101` for type-narrowing asserts) are on too;
  pagebuilder's and news' ETag hashes say `usedforsecurity=False`, and each
  deliberate production case carries a `# noqa: Sxxx` with its reason.
- **CI runs images and newsletter through a real broker** (#339). Every e2e
  spec runs Celery eager, which has its own code path, so the one production
  uses had unit tests only. The new job `Background tasks (Redis + Celery
  worker)` starts the host non-eager on Postgres with a Redis service, one
  worker (`images`, `newsletter`, `celery` queues) and one beat, and
  `scripts/bg_tasks_smoke.py` uploads an image and waits for its pipeline to
  settle, then imports a subscriber and sends a campaign on the console
  transport until the `newsletter.dispatch` beat marks it sent. The host,
  worker and beat logs are printed when it fails. `docs/module-layout.md` now
  says new background work goes through `background_tasks`, and lists the
  in-process loops, post-response jobs and `on_commit` tasks as legacy, to move
  when next touched.

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
