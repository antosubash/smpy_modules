# Newsletter PR 3: campaigns, content and test send — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An editor can create a draft campaign, write it in a newsletter-only Puck editor, insert
news article and page cards, preview the server-rendered email and send a `[TEST]` to up to five
addresses over SMTP (or the console transport), with the newsletter settings page to configure all of it.

**Architecture:** The body is a list of Puck items (`{type, props}`) validated by a pydantic
discriminated union. One Python renderer turns it into table-based, inline-styled HTML plus a
plain-text part. The preview iframe and the test send both use that renderer. Cards are snapshotted
through `news.contracts.articles` and a new `pagebuilder.contracts.cards`, and only optional
integrations import them. The transport seam (`smtp` through aiosmtplib, `console` with a capture
outbox) is shared with PR 4. Test sends write `newsletter_send_attempt` rows before they check the
rolling budget, so they count against the daily cap (spec amendment 4).

**Tech Stack:** FastAPI, SQLModel, pydantic v2, aiosmtplib, email-validator, stdlib `html.parser`,
aiosmtpd (tests), React 19 + Inertia, `@puckeditor/core` 0.24, vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`. The final "Amendments"
override the text above them. Roadmap: `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`.
PR 2 ledger: `.superpowers/sdd/2026-11-03-newsletter-pr2-scaffold/progress.md`, `final-review.md`.

## Rulings (decided here; cost if wrong in each)

- **R1. Unsubscribe URL and token without a send row.** A test send or preview has no
  `newsletter_send` row and no MAC. `{{unsubscribe_url}}`, the footer link and the
  `List-Unsubscribe` header all point at `<public_base_url>/newsletter/u/test`
  (`constants.TEST_UNSUBSCRIBE_TOKEN = "test"`). PR 4's route must answer it the way it answers a
  forged token: the same page, and a POST that changes nothing. Test sends still carry both
  `List-Unsubscribe*` headers and `Precedence: bulk`, so an operator can check the DKIM `h=` list
  (amendment 10). Tracking is never added (spec). — Cost if wrong: PR 4 must not 500 on `test`.
- **R2. An extra that is not installed.** `content/integrations/` is the only package that imports
  `news` or `pagebuilder`. Each import is deferred and guarded (news' `integrations/pagebuilder.py`
  is the precedent). `available(app)` is true only when the package imports *and* the module is
  mounted (`app.state.news` / `app.state.pagebuilder`). The editor's Inertia props carry
  `capabilities: {news, pagebuilder}`. The Puck config always *defines* both card blocks, so an
  existing card stays visible, deletable and rendered from its snapshot. When the capability is
  off, the config hides them from the palette (a category with `visible: false`) and disables the
  picker and Refresh with a translated note. The server answers the card, media and refresh
  routes with 409 `integration_unavailable`. — Cost if wrong: a stray card renders from a stale
  snapshot, which is still the sent content.
- **R3. Image source = URL, plus a picker over pagebuilder media through a contract.** No upload to
  file storage in PR 3: file_storage downloads are permission-gated, so the image would be broken
  in every inbox (branding serves its own anonymous route for this reason). The image block stores
  `src` (http(s), protocol-relative or site-relative). When pagebuilder is available, the picker
  lists `pagebuilder.contracts.cards.search_media_cards` (raster images only, never
  `image/svg+xml`). — Cost if wrong: uploads come later as their own route.
- **R4. Rich-text sanitising = one allow-list re-serialiser, applied at save *and* at render.**
  `content/richtext.py` parses with stdlib `HTMLParser` and *emits* only `p br strong em u s a ul
  ol li blockquote`, mapping `b→strong` and `i→em`. It keeps no attributes except `a[href]`, which
  must pass `urls.check_link`. All text is escaped. The contents of
  `script style iframe object embed template svg math head title noscript` are dropped; any other
  tag is unwrapped and its text kept. Nesting depth is capped at 20. Because output is built,
  never filtered, nothing unknown can pass through. The stored value is the cleaned form. The
  renderer cleans again, so a row written around the API is still safe. The admin preview is an
  `<iframe sandbox="" srcDoc>`, with no scripts and no same-origin, as a second layer. No new
  dependency (not nh3 or bleach). — Cost if wrong: Puck formatting outside the list (headings,
  code) is flattened to text.
- **R5. Renderer snapshot tests = golden files, with no new dependency.** The goldens live in
  `modules/newsletter/tests/content/golden/<case>.html|.txt` and are compared byte-exact. Set
  `NEWSLETTER_UPDATE_GOLDEN=1` to rewrite them, and review the diff in the commit. Structural
  assertions sit alongside: no `<script`, no `style=` from input, every `<img src>` and `<a href>`
  absolute, and the footer present. — Cost if wrong: an intended HTML change touches the goldens.
- **R6. Absolute URLs.** The base is the host's `public_base_url`
  (`app.state.sm.settings.public_base_url`), never the request `Host`. Snapshots store what the
  contract returns: `ArticleCard.path` is site-relative and locale-prefixed except for the default
  language, and `image_url` may be relative. The **renderer** makes them absolute (`urls.absolute`),
  so a later base change still works. With no base set, the preview renders relative URLs and the
  warning `relative_urls`. A test send refuses with 422 `public_base_url_required`.
- **R7. Branding = the SYSTEM theme** (`app.state.branding.settings`: `app_name`, `primary_color`,
  `logo_file_id`), not a tenant's override. The sender identity is SYSTEM scope (spec), and PR 4's
  worker has no request. The logo URL is branding's own anonymous asset route
  (`branding.shared_props.asset_url(branding.constants.LOGO_URL, id)`), made absolute. The import
  is guarded: without branding, the app name is `settings.from_name` (or `"Newsletter"`), the accent
  is `#2563eb` and there is no logo. — Cost if wrong: an org's own logo is not used.
- **R8. Body format = Puck `content` items** `[{"type": "Heading", "props": {"id": …}}]`, at most
  200, with unique ids. Puck's `root` is not stored. Unknown types and unknown props get 422
  `invalid_body` (`extra="forbid"`). The error names the path and never echoes the input.
- **R9. Cards are snapshotted server-side.** `POST /api/newsletter/cards/snapshot {kind, source_id}`
  returns the props, read through the contract. *Refresh* is server-side
  (`POST /campaigns/{id}/cards/refresh {block_id}`). It rewrites that block's snapshot in the
  stored draft. A source that is now unpublished, trashed or gone gets 409 `card_source_gone`, and
  the snapshot is kept.
- **R10. Settings page writes.** `GET /api/newsletter/settings` needs `newsletter.manage`.
  `PUT /api/newsletter/settings` needs `newsletter.manage` **and** `settings.edit`, the same as
  PR 2's password PUT (PR 2's Important 1 / Task F1 rule). A PUT that changes `smtp_host`,
  `smtp_port`, `smtp_security` or `smtp_username` also clears `smtp_password` in the same apply,
  and answers `password_cleared: true`. So nobody can point the relay at another server and
  harvest the stored credential at AUTH. The page warns before saving.
- **R11. Test-send budget = write, then check.** Pending `SendAttempt(kind="test")` rows are
  inserted and committed first. Then the rolling 24 h and 60 s windows are counted across every
  tenant (`pending`, `accepted` and `unknown` count, `rejected` does not). If either total is over
  the limit, our rows become `rejected` (`detail="over_budget"`) and the call answers 429
  `send_budget_exhausted` with nothing sent. Two racers can both refuse, but never both exceed.
  This needs no lock (PR 4's dispatcher lock is separate). Every row is committed before its SMTP
  call, so a crash leaves it `pending`, which still counts.
- **R12. Footer language** = the host's `i18n_default_locale`. The strings come from the
  `newsletter.email.*` catalogue keys through `app.state.sm.i18n_registry`, falling back to the
  package's `en.json`. A per-campaign or per-subscriber locale is PR 4's call.
- **R13. Records caller roles.** `can_read_list` needs `CallerRoles`, which newsletter cannot build
  itself (`type_grants`' wildcard rule is records'). Records adds
  `caller_roles(request) -> CallerRoles` to `sm_records.contracts.newsletter`, a wrapper over
  `sm_records.web.deps.caller_roles`. Setting or changing a campaign's `list_type_key` requires
  the list to be one of `subscription_lists(tenant)` and `can_read_list(..., roles=caller_roles(request))`.
- **R14. Audience in PR 3 is `all` only.** `segment:`/`tag:` get 422 `audience_unsupported` until
  PR 6 and PR 4.
- **R15. Concurrency.** A PATCH carries `expected_updated_at`. A mismatch gets 409 `stale`, and a
  non-draft gets 409 `not_a_draft`. The editor autosaves with a 1.5 s debounce. On `stale` it
  stops and asks the user to reload.

## Global Constraints

- Before **every** test or tsc/vitest run: `~/.claude/bin/wait-for-headroom` (exit 1 → stop and
  report). `PYTEST_WORKERS=8` cap. **Targeted tests only** (the files the task names). No full
  suites: `/ship` runs them once.
- Use `/usr/bin/ps`, never `ps` (it is aliased to `pnpm start`). One plain command per Bash call.
  Use literal paths.
- Never run a repo-wide `ruff format`. Format only the files you touched (`uv run ruff format <files>`).
- No secrets in commits. Never log, return or echo `smtp_password`, the decrypted password or an
  SMTP AUTH exchange.
- 300-line cap on every `.py`/`.ts`/`.tsx` (`scripts/check_file_size.py`). At 280+, split by
  responsibility.
- Pages rule: only real Inertia pages under `sm_newsletter/pages/` (`.tsx` with `export default`).
- Locales: every key goes into `en.json` and `de.json` in the same commit
  (`uv run python scripts/check_locales.py`). Every UI string goes through `t(keys.newsletter.…)`
  with no `defaultValue`.
- `scripts/check_hardcoded_strings.py`: permissions are `PERM_*`, page names are `_PAGE_*`
  constants in `core/constants.py`.
- Every admin router lists `Depends(bind_admin)` **first**, then `RequiresPermission(PERM_*)`. The
  API router is mounted under `RequiresCsrf()` (already in `module.py`). Views share the CSRF token.
- Card and media lookups go **only** through `news.contracts.articles` and `pagebuilder.contracts.*`.
  Lists and roles go **only** through `sm_records.contracts.newsletter`. Never import another
  module's tables or services.
- A published module never pins `==`. Each sibling requirement gets a `>=` floor and a
  `# floor: <reason>` comment (`scripts/check_rules.py`).
- Newsletter reads no environment variables. New settings fields go into `NewsletterSettings`.
- Every Core statement over a newsletter table pins `tenant_id`, except the budget count, which
  is deliberately cross-tenant (R11) and runs under the framework's `all_tenants()` plus
  `tenancy.all_tenants(stmt)`.
- Python tests: `uv run --directory modules/newsletter pytest <paths> -q -p no:cacheprovider`. Add
  Postgres where a task says so:
  `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test`.
- JS: `npx vitest run modules/newsletter` and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`.

## Review Focus

1. **Rich text pasted from Google Docs or Word** (`<span style>`, `<b id="docs-internal…">`,
   `<img onerror>`, `<a href="javascript:">`, nested tables). Expected: clean allowed markup with
   the text kept and nothing executable. Pinned in Task 5 (`test_google_docs_paste`).
2. **A card whose article is later unpublished, trashed, deleted or in another tenant.** Expected:
   Refresh answers `card_source_gone`, the snapshot and rendered email are unchanged, and no
   cross-tenant read happens. Pinned in Task 8.
3. **URL edges**: `public_base_url` blank, with a trailing slash, or with a path; `//cdn/x.png`;
   `/media/…`; `mailto:`; `javascript:`; `data:`. Expected: absolute https URLs in the email; refusal
   at validation for unsafe schemes. Pinned in Tasks 4 and 6.
4. **Two editor tabs, or an autosave after a status change.** Expected: 409 `stale` /
   `not_a_draft`, never a silent overwrite. Pinned in Task 7.
5. **Test-send input**: uppercase, duplicate or padded addresses; six addresses; CR/LF in an
   address or subject; a cap with 2 left and 3 asked. Expected: normalised and deduped, 422 for the
   six or for an injection, and 429 with nothing sent and the ledger rows `rejected`. Pinned in
   Task 11.

---

### Task 1: Dependencies, extras and the layout move

**Files:**
- Modify: `modules/newsletter/pyproject.toml`, `modules/newsletter/package.json`, `uv.lock`
- Move (moves only): `sm_newsletter/web/schemas.py` → `sm_newsletter/web/schemas/settings.py`
  (with `web/schemas/__init__.py`); `sm_newsletter/web/settings_service.py` →
  `sm_newsletter/web/services/settings.py`; `sm_newsletter/web/endpoints/api.py` →
  `sm_newsletter/web/endpoints/settings_api.py`. Update the imports in `module.py` and tests.
- Test: `modules/newsletter/tests/core/test_packaging.py`

- [ ] **Step 1: Failing test** `test_extras_and_floors`. Parse `pyproject.toml` (tomllib) and
  assert the following:
  - `optional-dependencies["news"] == ["simple_module_news>=0.0.13,<0.1"]` and
    `["pagebuilder"] == ["simple_module_pagebuilder>=0.0.13,<0.1"]`;
  - `aiosmtplib>=3.0,<6` and `email-validator>=2.1` are in `dependencies`;
  - `aiosmtpd>=1.4.6` is in `dev`.
  Add `test_no_eq_pins`: no dependency uses `==`.
- [ ] **Step 2: Run it.** `uv run --directory modules/newsletter pytest tests/core/test_packaging.py -q -p no:cacheprovider`. It should FAIL.
- [ ] **Step 3: Edit `pyproject.toml`.**
  - Add the deps and extras. Floor comments, exact:
    - `# floor: 0.0.13 — contracts.articles (newsletter PR 1, #306); raise to the release that first ships it`
    - `# floor: 0.0.13 — contracts.cards (newsletter PR 3); raise to the release that first ships it`
  - Reword the records floor comment to name `contracts.newsletter.caller_roles (newsletter PR 3)`
    as well.
  - Add `[tool.uv.sources]` entries `simple_module_news` and `simple_module_pagebuilder`, both
    `{ workspace = true }`.
  - Add `**/*-test-support.tsx` to the wheel `exclude` if it is missing.
- [ ] **Step 4: Edit `package.json`.** Add `peerDependencies`:
  - `@inertiajs/react ^3.9.1`, `@puckeditor/core ^0.24.0`, `@simple-module-py/ui *` and
    `react-dom ^19.3.1`, with the versions copied from `modules/news/package.json`.
- [ ] **Step 5: Lock and move.** Run `uv lock`, then make the three moves with `git mv` and fix
  the imports.
- [ ] **Step 6: Run the checks.** Run the packaging test, `tests/web/test_smtp_password.py` and
  `uv run python scripts/check_rules.py`. Expected: PASS.
- [ ] **Step 7: Commit.** Two commits: `chore(newsletter): move web schemas/services into
  packages (moves only)`, then `build(newsletter): news/pagebuilder extras, smtp deps`.

### Task 2: Records `caller_roles` contract (R13)

**Files:**
- Modify: `modules/records/sm_records/contracts/newsletter.py` (add the function and `__all__`)
- Test: `modules/records/tests/public_submissions/test_newsletter_contract_lists.py`

**Interfaces:** Produces `sm_records.contracts.newsletter.caller_roles(request) -> CallerRoles`, the
roles of the request's user plus its `records.type.<key>` grants, and `CallerRoles([])` when
anonymous.

- [ ] **Step 1: Failing tests.**
  - `test_caller_roles_from_request`: a stub request with `state.user.roles=["editor"]` and
    `state.resolved_permissions={"records.type.news_list"}` gives `list(r) == ["editor"]` and
    `r.granted_types == {"news_list"}`.
  - `test_caller_roles_wildcard_role_has_no_type_grants`: an admin role holding the wildcard gets
    `granted_types == frozenset()`.
  - Both feed `can_read_list` for a list with `allowed_roles=["x"]`: True for the grant, False
    without it.
- [ ] **Step 2: Run it.** `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_contract_lists.py -q -p no:cacheprovider`. It should FAIL.
- [ ] **Step 3: Implement** a thin wrapper over `sm_records.web.deps.caller_roles`, imported inside
  the function to keep contracts import-light. Keep the file under 280 lines.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(records): contracts.newsletter.caller_roles for per-list checks`

### Task 3: Pagebuilder `contracts/cards.py` (pages and media for email)

**Files:**
- Create: `modules/pagebuilder/pagebuilder/contracts/cards.py`
- Modify: `modules/pagebuilder/pagebuilder/contracts/__init__.py` (re-export)
- Test: `modules/pagebuilder/tests/content/test_cards_contract.py`

**Interfaces (Produces):**
```python
class PageCard(BaseModel, frozen=True): id: int; title: str; excerpt: str; image_url: str; path: str; locale: str
class MediaCard(BaseModel, frozen=True): id: int; filename: str; content_type: str; path: str
async def search_page_cards(app, session, *, tenant_id: str, pattern: str, limit: int = 20, locale: str | None = None) -> list[PageCard]
async def get_page_card(app, session, *, tenant_id: str, page_id: int) -> PageCard | None
async def search_media_cards(app, session, *, tenant_id: str, pattern: str, limit: int = 20) -> list[MediaCard]
async def get_media_card(app, session, *, tenant_id: str, media_id: int) -> MediaCard | None
```
- Pages are published and not trashed only.
  - `excerpt` = `meta_description or ""`, `image_url` = `og_image or ""`.
  - `path` = `locales.public_path(settings.public_route_prefix, slug, locale)`.
- Media are `image/*` except `image/svg+xml`. `path` = `media_url(settings.media_url_prefix, filename, tenant_id)`.
- Settings are read from `app.state.pagebuilder.settings`. When it is absent (not mounted), the
  functions answer `[]` / `None`.
- The tenant is pinned with a `WHERE` *and* a scope that refuses another bound tenant
  (`TenantIsolationError`) and binds `tenant_context(tenant_id)` when none is (spec amendment 6's
  semantics).
- `limit` and `pattern` are checked as in `search.py`, and the limit check is reused.

- [ ] **Step 1: Failing tests.**
  - `test_page_card_published_only` (draft → None, trashed → None);
  - `test_page_card_path_is_locale_prefixed` (default locale has no prefix, `de` → `/de/p/slug`);
  - `test_other_tenant_is_none`;
  - `test_bound_other_tenant_raises`;
  - `test_media_cards_exclude_svg_and_non_images`;
  - `test_unmounted_app_answers_nothing` (an `app.state` without `pagebuilder`);
  - `test_limit_validated` (0 and 101 → ValueError).
- [ ] **Step 2: Run it.** `uv run --directory modules/pagebuilder pytest tests/content/test_cards_contract.py -q -p no:cacheprovider`. It should FAIL.
- [ ] **Step 3: Implement** `cards.py` (under 200 lines).
- [ ] **Step 4: Run it.** Expected: PASS. Repeat on Postgres
  (`SM_TEST_DATABASE_URL=…/smpy_pagebuilder_test`, if that database exists; otherwise note the skip).
- [ ] **Step 5: Commit.** `feat(pagebuilder): contracts.cards — page and media cards for newsletters`

### Task 4: Block model, URL rules and merge fields

**Files:**
- Create: `sm_newsletter/content/__init__.py`, `content/blocks.py`, `content/urls.py`, `content/merge.py`
- Modify: `sm_newsletter/core/errors.py` (add `InvalidBody`, 422, code `invalid_body`)
- Test: `tests/content/test_blocks.py`, `tests/content/test_urls.py`, `tests/content/test_merge.py`

**Interfaces (Produces):**
```python
# urls.py
UNSUBSCRIBE_TAG = "{{unsubscribe_url}}"
def check_link(value: str) -> str      # http(s)://host…, mailto:, "/path" (not "//"), or exactly UNSUBSCRIBE_TAG; ≤2000; no whitespace/control chars
def check_image(value: str) -> str     # "" | http(s):// | //host/… | "/path"; ≤2000
def absolute(base: str, url: str) -> str   # "/x"→base.rstrip("/")+"/x" (base "" → unchanged); "//h/x"→"https://h/x"; absolute/mailto/tag unchanged
def is_relative(url: str) -> bool
# merge.py
def check_merge(text: str) -> None     # ValueError on any {{…}} other than first_name[|fallback≤100, no | { }] or unsubscribe_url (no fallback)
def personalise_html(s: str, *, first_name: str | None, unsubscribe_url: str) -> str
def personalise_text(s: str, *, first_name: str | None, unsubscribe_url: str) -> str
# blocks.py
BLOCK_TYPES = ("Heading", "RichText", "Image", "Button", "Divider", "Spacer", "ArticleCard", "PageCard")
MAX_BLOCKS = 200
Block = Annotated[HeadingBlock | RichTextBlock | ImageBlock | ButtonBlock | DividerBlock | SpacerBlock | ArticleCardBlock | PageCardBlock, Field(discriminator="type")]
def parse_body(raw: object) -> list[Block]    # raises InvalidBody(detail="body[3].props.href: …") without input
def dump_body(blocks: list[Block]) -> list[dict]
```

**Props.** Every model uses `extra="forbid"` and has `id: str` (`^[A-Za-z0-9_-]{1,64}$`).
- Heading: `text` 1..200, no newline; `level` `"1"|"2"` (default `"2"`); `align` `left|center`.
- RichText: `html` ≤20000, cleaned by Task 5's `richtext.clean` in a validator. Wire that in
  Task 5; until then, store as given.
- Image: `src` (`check_image`, non-empty); `alt` ≤300; `href` is `check_link` or None; `width` 1..600 (default 600).
- Button: `label` 1..80; `href` (`check_link`); `align` (default `center`).
- Divider: no props.
- Spacer: `size` `sm|md|lg`.
- ArticleCard / PageCard: `source_id` > 0; `title` ≤300; `excerpt` ≤1000; `image_url`
  (`check_image` or ""); `url` (`check_link`); `locale` ≤16; `snapshot_at` (an aware datetime).

`check_merge` runs on heading text, button label, rich-text text and image alt.

**Merge tags.** An href may hold `{{` only as exactly `UNSUBSCRIBE_TAG`. In `personalise_html`,
`first_name` is HTML-escaped and stripped. When it is empty, the fallback (already escaped by the
renderer) is used. `unsubscribe_url` is HTML-escaped.

- [ ] **Step 1: Failing tests.**
  - urls:
    - `test_check_link_refuses` parametrised over `javascript:x`, `data:text/html,x`,
      `vbscript:`, `//evil`, `http://a b`, `"\nhttp://a"` and `{{first_name}}`;
    - `test_absolute` over the cases `("https://ex.org/", "/de/p/x") → "https://ex.org/de/p/x"`,
      `("https://ex.org/base", "/m.png") → "https://ex.org/base/m.png"`,
      `("", "/x") → "/x"`, `("https://ex.org", "//cdn/i.png") → "https://cdn/i.png"` and
      `("https://ex.org", "mailto:a@b") → "mailto:a@b"`.
  - merge:
    - `test_unknown_tag_refused` (`{{last_name}}`);
    - `test_fallback_rules` (`{{first_name|Friend}}` ok, fallback of 101 chars refused,
      `{{unsubscribe_url|x}}` refused);
    - `test_personalise_html_escapes`: `first_name="<b>"` → `&lt;b&gt;`;
    - `test_empty_first_name_uses_fallback`;
    - `test_text_fallback_raw` (`Tom & Jerry` stays raw in text).
  - blocks:
    - `test_round_trip` (all 8 types parse and dump to equal JSON);
    - `test_unknown_type_422`;
    - `test_extra_prop_422`;
    - `test_duplicate_ids_422`;
    - `test_201_blocks_422`;
    - `test_error_never_echoes_input`: a 5000-char `<script>` heading → the detail does not
      contain `script`.
- [ ] **Step 2: Run them.** They should FAIL.
- [ ] **Step 3: Implement** the three files.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): email block model, URL and merge-field rules`

### Task 5: Rich-text sanitiser (R4)

**Files:**
- Create: `sm_newsletter/content/richtext.py`
- Modify: `content/blocks.py` (RichText validator calls `clean`)
- Test: `tests/content/test_richtext.py`, plus the fixture `tests/content/fixtures/gdocs_paste.html`
  (a real-shaped Google Docs clipboard payload)

**Interfaces (Produces):**
```python
ALLOWED_TAGS = frozenset({"p","br","strong","em","u","s","a","ul","ol","li","blockquote"})
def clean(raw: str) -> str                         # canonical, attribute-free except a[href]
def to_email_html(cleaned: str, *, accent: str) -> str   # same tree, each tag gets its inline style (styles from render/styles.py)
def to_text(cleaned: str) -> str                   # blank line between blocks, "- " / "1. " list items, "label (url)" for links whose label != url
```

- [ ] **Step 1: Failing tests.**
  - `test_drops_script_and_contents`;
  - `test_strips_event_handlers` (`<p onclick=x>` → `<p>`);
  - `test_javascript_href_dropped_keeps_text`;
  - `test_b_i_mapped`;
  - `test_unknown_tag_unwrapped` (`<span style>hi</span>` → `hi`);
  - `test_entities_escaped` (`<p>&lt;script&gt;</p>` stays escaped);
  - `test_unclosed_tags_closed`;
  - `test_depth_cap`;
  - `test_idempotent` (`clean(clean(x)) == clean(x)` for each fixture);
  - `test_google_docs_paste` (the fixture gives the expected cleaned string written in the test);
  - `test_to_text_lists_and_links`;
  - `test_merge_tag_in_text_survives` (`{{first_name|Hi}}` unchanged).
- [ ] **Step 2: Run it.** It should FAIL.
- [ ] **Step 3: Implement** with `html.parser.HTMLParser(convert_charrefs=True)` and a stack, under
  250 lines. Wire the validator in `blocks.py`.
- [ ] **Step 4: Run** `tests/content/test_richtext.py tests/content/test_blocks.py`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): allow-list rich-text sanitiser`

### Task 6: The email renderer (HTML + text, footer, branding)

**Files:**
- Create: `sm_newsletter/content/render/__init__.py` (`render`, `personalise`),
  `render/types.py` (dataclasses), `render/html.py` (shell and block emitters),
  `render/text.py`, `render/footer.py`, `render/styles.py` (colours, fonts, spacing constants),
  `sm_newsletter/content/context.py`
- Modify: `sm_newsletter/locales/en.json`, `de.json` (`email.footer_reason`, `email.unsubscribe`)
- Modify: `sm_newsletter/core/constants.py` (`TEST_UNSUBSCRIBE_TOKEN = "test"`, `DEFAULT_ACCENT = "#2563eb"`)
- Test: `tests/content/test_render.py`, `tests/content/test_render_golden.py`,
  `tests/content/test_context.py`, plus goldens `tests/content/golden/{kitchen_sink,minimal,no_base_url}.{html,txt}`

**Interfaces (Produces):**
```python
@dataclass(frozen=True) class Branding: app_name: str; accent: str; logo_url: str
@dataclass(frozen=True) class FooterCopy: reason: str; unsubscribe: str      # reason already has {app_name} substituted
@dataclass(frozen=True) class RenderContext: base_url: str; branding: Branding; physical_address: str; footer: FooterCopy; locale: str
@dataclass(frozen=True) class RenderInput: subject: str; preheader: str; blocks: list[Block]
@dataclass(frozen=True) class RenderedTemplate: subject: str; html: str; text: str; warnings: tuple[str, ...]
@dataclass(frozen=True) class RenderedEmail: subject: str; html: str; text: str
def render(inp: RenderInput, ctx: RenderContext) -> RenderedTemplate
def personalise(t: RenderedTemplate, *, first_name: str | None, unsubscribe_url: str) -> RenderedEmail
# context.py
def render_context(app) -> RenderContext          # R6, R7, R12
def test_unsubscribe_url(base_url: str) -> str    # f"{base}{PUBLIC_PREFIX}u/{TEST_UNSUBSCRIBE_TOKEN}"
```
- **Warnings** (exact strings): `relative_urls`, `physical_address_missing`, `empty_body`.
- **HTML shape**:
  - an XHTML-ish doctype with `<html lang=locale>`, meta charset and viewport, and `<title>` = the
    escaped subject;
  - a hidden preheader `div` (`display:none;max-height:0;overflow:hidden;mso-hide:all`);
  - an outer `table width="100%" role="presentation"` with a `#f4f4f5` background, and an inner
    600 px table (`width="600"`, `max-width:600px`);
  - a header row with the logo (`width<=200`, alt = app name) or the app name;
  - one `<tr><td>` per block;
  - buttons as a bulletproof table cell `bgcolor=accent`;
  - cards as image + title link + excerpt + a "Read more" link using the accent colour;
  - a footer row with the reason, the physical address (escaped, newlines → `<br>`) and
    `<a href="{{unsubscribe_url}}">`.
- **Never** emit `<script>`, `<style>` blocks or `class`.
- Every URL goes through `urls.absolute(ctx.base_url, …)`. Rich text goes through
  `richtext.clean` then `to_email_html`.
- **Text part**:
  - headings are underlined with `=` (level 1) or `-` (level 2);
  - buttons are `Label: url`;
  - cards are `Title\nExcerpt\nurl`;
  - a divider is `----`;
  - the footer is `--\nreason\naddress\nunsubscribe: {{unsubscribe_url}}`.
- **`render_context` sources**:
  - `app.state.sm.settings.public_base_url` and `i18n_default_locale`;
  - `app.state.sm_newsletter.settings` (`physical_address`, `from_name`);
  - `app.state.branding.settings` through a guarded import;
  - `app.state.sm.i18n_registry.messages(locale)`, falling back to the package `en.json`.

- [ ] **Step 1: Failing tests.**
  - `test_render`:
    - `test_footer_always_present` (empty body);
    - `test_no_script_ever` (rich text with script plus a heading `<script>`);
    - `test_all_urls_absolute` (regex over `href=`/`src=`, with `UNSUBSCRIBE_TAG` exempt);
    - `test_relative_warning_without_base`;
    - `test_physical_address_missing_warning`;
    - `test_preheader_hidden`;
    - `test_subject_merge` (`Hi {{first_name|there}}` → `Hi there` / `Hi Ann`);
    - `test_unsubscribe_tag_replaced_everywhere` (the HTML footer, the text and a button href);
    - `test_first_name_html_injection_escaped`.
  - `test_render_golden`: three cases built from fixed blocks, a fixed `snapshot_at` and a fixed
    `RenderContext`, compared to the goldens (R5).
  - `test_context`:
    - `test_branding_absent_defaults`;
    - `test_logo_url_absolute`;
    - `test_footer_copy_de` (a registry with `de` → the German string);
    - `test_base_from_host_settings_not_request`.
- [ ] **Step 2: Run them.** They should FAIL.
- [ ] **Step 3: Implement.** Generate the goldens once with `NEWSLETTER_UPDATE_GOLDEN=1`, then read
  them and check them by hand in Gmail-safe terms: tables, inline styles, no `<style>`.
- [ ] **Step 4: Run** `tests/content/` and `uv run python scripts/check_locales.py`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): table-based email renderer with plain-text part`

### Task 7: Campaign drafts — service, list access, API and test harness

**Files:**
- Create: `sm_newsletter/campaigns/__init__.py`, `campaigns/drafts.py`, `campaigns/access.py`,
  `sm_newsletter/web/schemas/campaigns.py`, `sm_newsletter/web/endpoints/campaigns_api.py`,
  `sm_newsletter/web/endpoints/__init__.py` (`build_api_router()` including every API router)
- Create: `tests/support/app.py` (shared app builder, extracted from `tests/web/test_smtp_password.py`, which now uses it)
- Modify: `module.py` (`register_routes` includes `build_api_router()`), `core/errors.py`
- Test: `tests/campaigns/test_drafts.py`, `tests/web/test_campaigns_api.py`

**Interfaces (Produces):**
```python
# errors: NotADraft(409,"not_a_draft"), StaleCampaign(409,"stale"), UnknownList(422,"unknown_list"),
#         ListForbidden(403,"list_forbidden"), AudienceUnsupported(422,"audience_unsupported")
async def check_list(session, *, tenant_id: str, type_key: str, roles) -> None
async def create_draft(session, *, tenant_id: str, data: CampaignCreate, roles) -> Campaign
async def get_campaign(session, *, tenant_id: str, campaign_id: int) -> Campaign          # NotFound
async def list_campaigns(session, *, tenant_id: str, status: str | None, q: str | None, offset: int, limit: int) -> tuple[list[Campaign], int]
async def update_draft(session, *, tenant_id: str, campaign_id: int, patch: CampaignPatch, roles) -> Campaign
async def delete_draft(session, *, tenant_id: str, campaign_id: int) -> None
# schemas
class CampaignCreate: name(1..200), list_type_key(1..64), subject="", preheader=""
class CampaignPatch: name|subject|preheader|from_name|reply_to(EmailStr|None)|list_type_key|audience|body: all optional; expected_updated_at: datetime | None
class CampaignSummary: id,name,subject,status,list_type_key,updated_at,recipient_count,sent_count
class CampaignDetail(CampaignSummary): preheader, from_name, reply_to, audience, body: list[dict]
# tests/support/app.py
async def build_app(*, multi: bool = False, session: bool = False, settings: dict | None = None) -> tuple[FastAPI, Any]
#   _Auth: x-perms (csv) → resolved_permissions, x-roles → user.roles, x-tenant → request.state.tenant_id
```
- Subject, preheader and from_name refuse CR/LF (422).
- `list` orders by `updated_at desc, id desc`. `q` matches `name ilike` (escaped), and `limit` ≤100.
- Every query pins `Campaign.tenant_id == tenant_id`.
- `body` goes through `parse_body`/`dump_body`.
- Routes, router `dependencies=[Depends(bind_admin)]`:
  - `GET /campaigns` (view);
  - `POST /campaigns` (edit, 201);
  - `GET /campaigns/{id}` (view);
  - `PATCH /campaigns/{id}` (edit);
  - `DELETE /campaigns/{id}` (edit, 204);
  - `GET /lists` (view): the `subscription_lists` the caller can read.
- Roles come from `caller_roles(request)` (Task 2).

- [ ] **Step 1: Failing tests.** All on SQLite, with lists seeded through `tests/support/records_seed.seed_list`.
  - drafts:
    - `test_create_requires_known_list`;
    - `test_create_refused_for_narrowed_list` (`allowed_roles=["x"]`, caller roles `[]` → `ListForbidden`);
    - `test_update_stale` (Review Focus 4);
    - `test_update_non_draft_409` (set status `scheduled` directly);
    - `test_delete_non_draft_409`;
    - `test_other_tenant_not_found` (create in `a`, get in `b`);
    - `test_audience_segment_unsupported`;
    - `test_body_validated`.
  - API:
    - `test_crud_round_trip`;
    - `test_permissions` (parametrised: view cannot POST, PATCH or DELETE; no perms → 403 on GET);
    - `test_multi_tenant_without_tenant_403_tenant_required`;
    - `test_write_without_csrf_403` (`session=True`);
    - `test_crlf_subject_422`.
- [ ] **Step 2: Run** `tests/campaigns/test_drafts.py tests/web/test_campaigns_api.py tests/web/test_smtp_password.py`. They should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS. Repeat on Postgres (the drafts file).
- [ ] **Step 5: Commit.** `feat(newsletter): draft campaign CRUD with per-list access`

### Task 8: Card integrations, snapshot and refresh

**Files:**
- Create: `sm_newsletter/content/integrations/__init__.py` (`capabilities(app) -> dict[str, bool]`),
  `integrations/news.py`, `integrations/pagebuilder.py`, `sm_newsletter/content/cards.py`,
  `sm_newsletter/web/schemas/cards.py`, `sm_newsletter/web/endpoints/cards_api.py`
- Modify: `core/errors.py` (`IntegrationUnavailable` 409 `integration_unavailable`,
  `CardSourceGone` 409 `card_source_gone`, `BlockNotFound` 404 `block_not_found`)
- Test: `tests/content/test_integrations.py`, `tests/content/test_cards.py`, `tests/web/test_cards_api.py`

**Interfaces (Produces):**
```python
@dataclass(frozen=True) class CardHit: kind: Literal["article","page"]; source_id: int; title: str; excerpt: str; image_url: str; url: str; locale: str
@dataclass(frozen=True) class MediaHit: id: int; filename: str; url: str   # url = path as the contract returns it
def like_pattern(q: str) -> str        # escapes \ % _ ; "%q%"; q stripped, ≤100
# integrations/news.py
def available(app) -> bool
async def search(app, session, *, tenant_id: str, q: str, locale: str | None) -> list[CardHit]
async def card(app, session, *, tenant_id: str, source_id: int) -> CardHit | None
# integrations/pagebuilder.py — same two, plus:
async def search_media(app, session, *, tenant_id: str, q: str) -> list[MediaHit]
# cards.py
def snapshot_props(hit: CardHit, *, block_id: str, now: datetime) -> dict
async def snapshot(app, session, *, tenant_id: str, kind: str, source_id: int) -> dict   # IntegrationUnavailable / NotFound
async def refresh_block(app, session, *, tenant_id: str, campaign_id: int, block_id: str) -> Campaign
```
- Routes, all **edit**:
  - `GET /cards/articles?q=&locale=`;
  - `GET /cards/pages?q=&locale=`;
  - `POST /cards/snapshot {kind, source_id}` (returns props with a fresh `id`, `uuid4().hex[:12]`);
  - `GET /media?q=`;
  - `POST /campaigns/{id}/cards/refresh {block_id}` (returns `CampaignDetail`; non-draft → 409
    `not_a_draft`; a block that is not a card → 404 `block_not_found`).
- `refresh_block` keeps `id` and replaces every other prop.

- [ ] **Step 1: Failing tests.**
  - `test_integrations`:
    - `test_unavailable_when_not_mounted`;
    - `test_unavailable_when_import_blocked` (`monkeypatch.setitem(sys.modules, "news.contracts.articles", None)`);
    - `test_capabilities_dict`.
  - `test_cards`:
    - `test_snapshot_article_from_contract` (seed a published `news.models.NewsArticle`; the
      test DB adds news' metadata);
    - `test_refresh_updates_title`;
    - `test_refresh_unpublished_is_gone_and_keeps_snapshot` (Review Focus 2; also trashed, and
      other tenant);
    - `test_refresh_non_card_404`;
    - `test_like_pattern_escapes`.
  - `test_cards_api`:
    - `test_routes_409_when_unavailable`;
    - `test_view_only_403`;
    - `test_pages_via_contract`: monkeypatch `integrations.pagebuilder` to return fixed hits, and
      assert the contract is called with the bound tenant.
- [ ] **Step 2: Run them.** They should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): article and page cards snapshotted through contracts`

### Task 9: Preview endpoints

**Files:**
- Create: `sm_newsletter/web/endpoints/preview_api.py`, `sm_newsletter/web/schemas/preview.py`
- Test: `tests/web/test_preview_api.py`

**Interfaces:**
- `PreviewIn(subject, preheader, body: list[dict])`.
- `PreviewOut(subject: str, html: str, text: str, warnings: list[str])`.
- Routes:
  - `GET /campaigns/{id}/preview` (view): the saved draft;
  - `POST /preview` (edit): unsaved content.
- Both `personalise` with `first_name=None` and `unsubscribe_url=test_unsubscribe_url(base)` (R1).

- [ ] **Step 1: Failing tests.**
  - `test_preview_saved_matches_render` (same HTML as `render` + `personalise` called directly);
  - `test_preview_unsaved_validates_body` (bad body → 422 `invalid_body`);
  - `test_preview_warns_relative_without_base`;
  - `test_preview_permission` (view may GET and may not POST).
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): server-rendered preview API`

### Task 10: Transport seam — SMTP and console

**Files:**
- Create: `sm_newsletter/sending/__init__.py`, `sending/transport/__init__.py` (`transport_for`),
  `transport/base.py`, `transport/message.py`, `transport/smtp.py`, `transport/console.py`
- Modify: `core/errors.py` (`TransportUnavailable` 502 `transport_unavailable`; the detail never
  holds credentials)
- Test: `tests/sending/test_message.py`, `tests/sending/test_smtp.py` (aiosmtpd), `tests/sending/test_console.py`

**Interfaces (Produces):**
```python
@dataclass(frozen=True) class OutgoingMessage: sender: str; to: str; subject: str; html: str; text: str; reply_to: str | None; headers: Mapping[str, str]
@dataclass(frozen=True) class DeliveryResult: outcome: Literal["accepted","rejected","unknown"]; code: int | None; detail: str   # detail ≤500
class TransportSession(Protocol):
    async def send(self, msg: OutgoingMessage) -> DeliveryResult
class Transport(Protocol):
    name: str
    supports_list_unsubscribe: bool
    def session(self) -> AbstractAsyncContextManager[TransportSession]   # raises TransportUnavailable on connect/TLS/auth failure
def build_mime(msg: OutgoingMessage) -> EmailMessage   # multipart/alternative (text, then html), Message-ID (sender's domain), Date
def unsubscribe_headers(url: str) -> dict[str, str]    # List-Unsubscribe: <url>, List-Unsubscribe-Post: List-Unsubscribe=One-Click, Precedence: bulk
def transport_for(settings: NewsletterSettings) -> Transport
# console.py
@dataclass(frozen=True) class CapturedMessage: tenant_id: str; to: str; subject: str; html: str; text: str; headers: dict[str, str]; at: datetime
def captured(tenant_id: str) -> list[CapturedMessage]           # newest first, from a deque(maxlen=50)
def add_capture_hook(fn: Callable[[CapturedMessage], None]) -> Callable[[], None]   # returns the remover
```
- **SMTP** uses `aiosmtplib.SMTP(hostname, port, use_tls=security=="tls",
  start_tls=security=="starttls", timeout=30)`, and `login` only when the username is set.
  `send` uses `mail()`, `rcpt()` and `data()` explicitly (amendment 2's boundary, reused in PR 4):
  - an `SMTPResponseException` from `mail`, `rcpt` or `data` is `rejected` with its code;
  - `SMTPServerDisconnected` or a timeout *during* `data` is `unknown`;
  - success is `accepted` with code 250.
- The password comes from `crypto.decrypt_value(settings.smtp_password, "smtp_password")`.
- **Console** logs `to` and `subject` only at INFO, captures under `bound_tenant()`, and returns
  `accepted`.
- Header values refuse CR/LF (a `ValueError` from `build_mime`).

- [ ] **Step 1: Failing tests.**
  - `test_message`:
    - `test_alternative_parts_order`;
    - `test_unsubscribe_headers_exact`;
    - `test_crlf_header_refused`;
    - `test_message_id_domain`.
  - `test_smtp` (an aiosmtpd `Controller` on 127.0.0.1 with a free port and a handler that can
    answer 250, 550 5.1.1 or 451, or drop during DATA):
    - `test_accepted_and_headers_arrive`;
    - `test_rcpt_550_rejected_with_code`;
    - `test_451_rejected_with_code`;
    - `test_disconnect_during_data_unknown`;
    - `test_auth_failure_raises_transport_unavailable_without_password_in_detail`
      (`caplog` holds no password).
  - `test_console`:
    - `test_capture_is_per_tenant`;
    - `test_hook_called_and_removed`.
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): transport seam with SMTP and console transports`

### Task 11: Attempt ledger, rolling budget and test send

**Files:**
- Create: `sm_newsletter/sending/ledger.py`, `sending/budget.py`, `sm_newsletter/campaigns/test_send.py`,
  `sm_newsletter/web/schemas/test_send.py`, `sm_newsletter/web/endpoints/test_send_api.py`
- Modify: `core/errors.py` (`SendBudgetExhausted` 429 `send_budget_exhausted`,
  `SenderNotConfigured` 422 `sender_not_configured`, `PublicBaseUrlRequired` 422 `public_base_url_required`)
- Test: `tests/sending/test_ledger.py`, `tests/campaigns/test_test_send.py`, `tests/web/test_test_send_api.py`

**Interfaces (Produces, PR 4 reuses the ledger and budget):**
```python
COUNTED_OUTCOMES = ("pending", "accepted", "unknown")
async def open_attempts(session, *, campaign_id: int | None, send_ids: list[int | None], kind: str, recipients: list[str], now: datetime) -> list[SendAttempt]
async def close_attempt(session, attempt: SendAttempt, result: DeliveryResult) -> None
async def attempts_since(session_factory, *, since: datetime) -> int      # own session; framework all_tenants() + tenancy.all_tenants(stmt); Core count over SendAttempt.__table__
@dataclass(frozen=True) class Budget: day_used: int; minute_used: int; daily_limit: int; per_minute_limit: int
    def exceeded(self) -> bool
async def current_budget(session_factory, settings, *, now: datetime) -> Budget
MAX_TEST_RECIPIENTS = 5
TEST_SUBJECT_PREFIX = "[TEST] "
@dataclass(frozen=True) class TestSendResult: recipient: str; outcome: str; code: int | None; detail: str
async def send_test(app, session, *, tenant_id: str, campaign_id: int, recipients: list[str], now: datetime | None = None) -> list[TestSendResult]
```
- **The flow in `send_test`** (R11):
  1. Load the campaign. Any status is allowed except `cancelled`.
  2. Check the sender configuration: `from_address` and `physical_address` are required, and
     `smtp_host` too for `smtp`. Otherwise `SenderNotConfigured`, and the detail names the field.
  3. Render. A `relative_urls` warning raises `PublicBaseUrlRequired`.
  4. `open_attempts`, then `finalize_session`.
  5. `current_budget`. If it is exceeded, mark every attempt `rejected`/`over_budget`, commit and
     raise.
  6. Open `transport.session()`. On `TransportUnavailable`, mark the attempts `rejected` with the
     error kind, commit and re-raise.
  7. For each recipient: `personalise(first_name=None, unsubscribe_url=test_unsubscribe_url(base))`,
     add the subject prefix, add `unsubscribe_headers` when the transport supports them, send, then
     `close_attempt` and commit.
- **Endpoint** `POST /campaigns/{id}/test-send` (**send** permission). Body:
  `TestSendIn(recipients: list[EmailStr], 1..5)`, stripped, lowercased and deduped before the
  count. Answers `TestSendOut(results: list[TestSendResult])`.

- [ ] **Step 1: Failing tests.**
  - ledger, on SQLite *and* Postgres:
    - `test_counts_every_tenant` (attempts in `a` and `b`, with `a` bound → counts both);
    - `test_rejected_not_counted`;
    - `test_window_edges` (fake clock: 24 h + 1 s ago is not counted).
  - test_send, with the console transport:
    - `test_prefix_and_footer_and_headers` (the captured subject starts with `[TEST] `, the HTML
      holds `/newsletter/u/test`, `List-Unsubscribe` is present);
    - `test_attempt_rows_kind_test_accepted`;
    - `test_cap_two_left_three_asked_sends_none` (Review Focus 5: `daily_limit=5` with 3 used →
      429, nothing captured, our 3 rows `rejected`);
    - `test_per_minute_limit`;
    - `test_missing_physical_address_422`;
    - `test_no_base_url_422`;
    - `test_transport_down_rows_rejected`;
    - `test_smtp_path_via_aiosmtpd` (one accepted, one 550 → per-address results).
  - API:
    - `test_six_addresses_422`;
    - `test_dedup_and_lowercase` (`[" A@x.org", "a@X.org"]` → one result);
    - `test_crlf_address_422`;
    - `test_edit_without_send_403`.
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS, with the ledger file on Postgres too.
- [ ] **Step 5: Commit.** `feat(newsletter): test send through the attempt ledger and daily cap`

### Task 12: Settings API and the console outbox

**Files:**
- Modify: `sm_newsletter/web/endpoints/settings_api.py`, `web/schemas/settings.py`, `web/services/settings.py`
- Create: `sm_newsletter/web/endpoints/outbox_api.py`
- Test: `tests/web/test_settings_api.py`, `tests/web/test_outbox_api.py`

**Interfaces:**
```python
SERVER_FIELDS = ("smtp_host", "smtp_port", "smtp_security", "smtp_username")
class SettingsOut: every NewsletterSettings field except smtp_password, + has_password: bool
class SettingsUpdate: same fields, all optional (from_address/reply_to: EmailStr | "")
class SettingsSaved(SettingsOut): password_cleared: bool
async def update_settings(app, db, changes: dict) -> bool    # returns password_cleared; validates merged values with NewsletterSettings.model_validate; one apply_changes_and_reload
```
- Routes:
  - `GET /settings` needs manage;
  - `PUT /settings` needs manage + `settings.edit` (R10);
  - `PUT /settings/smtp-password` is unchanged.
- `GET /outbox` (manage) is a 404 unless `transport == "console"`. It returns the bound tenant's
  `captured()` messages as JSON (the dev/e2e capture hook).

- [ ] **Step 1: Failing tests.**
  - `test_get_never_returns_password`;
  - `test_put_requires_both_perms` (parametrised);
  - `test_host_change_clears_password` (store a password, change `smtp_host` →
    `password_cleared` is true and the stored row is empty);
  - `test_unrelated_change_keeps_password`;
  - `test_invalid_port_422`;
  - `test_values_persist_and_hot_swap` (`app.state.sm_newsletter.settings` updated);
  - outbox: `test_404_on_smtp`, `test_lists_only_own_tenant`.
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): settings API; server change clears the SMTP password`

### Task 13: Views, menu and the route-guard matrix

**Files:**
- Create: `sm_newsletter/web/endpoints/views.py`, `web/endpoints/menu.py`, `web/endpoints/csrf.py`
  (`share_csrf_token`, copied from news)
- Modify: `module.py` (`view_router.include_router(views.router)`, `register_menu_items`),
  `core/constants.py`
- Modify: `sm_newsletter/locales/en.json`, `de.json` (`menu.group`, `menu.campaigns`, `menu.settings`)
- Test: `tests/web/test_views.py`, `tests/web/test_route_guards.py`

**Constants** (exact):
- `_PAGE_CAMPAIGNS = "Newsletter/Campaigns"`, `_PAGE_EDITOR = "Newsletter/CampaignEditor"`,
  `_PAGE_SETTINGS = "Newsletter/Settings"`;
- `MENU_GROUP = "Newsletter"`, `MENU_GROUP_KEY = "newsletter.menu.group"`;
- `MENU_URL = f"{VIEW_PREFIX}/"`, `SETTINGS_URL` (existing).
- The menu items are Campaigns (icon `mail`, order 300, `permissions=[PERM_VIEW]`) and Settings
  (icon `settings`, order 390, `permissions=[PERM_MANAGE]`).

**Views**, with router deps `[Depends(bind_admin), Depends(share_csrf_token)]`:
- `GET /` (view) → Campaigns: `{**view_props, can_edit, can_send}`.
- `GET /campaigns/{campaign_id}` (view; 404 through `get_campaign`) → CampaignEditor:
  `{**view_props, campaign_id, can_edit, can_send, capabilities, public_base_url_set, max_test_recipients: 5}`.
- `GET /settings` (manage) → Settings: `{**view_props, can_write: holds settings.edit}`.
- Permission flags come from `ensure_resolved_permissions(request)`.

- [ ] **Step 1: Failing tests.**
  - `test_route_guards` walks `app.routes` for every path under `/api/newsletter` and
    `/admin/newsletter`. It asserts each has `bind_admin` as its *first* dependency and at least
    one `RequiresPermission` whose permission is in `PERMISSIONS ∪ {PERM_SETTINGS_EDIT}`. Unsafe
    API methods must sit under `RequiresCsrf`.
  - `test_views`:
    - `test_editor_props` (capabilities false without news or pagebuilder);
    - `test_editor_unknown_campaign_404`;
    - `test_settings_view_needs_manage`;
    - `test_menu_items` (two items, keys present in `en.json`).
- [ ] **Step 2–4: Run → implement → run.** Also run `uv run python scripts/check_hardcoded_strings.py`
  and `check_locales.py`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): admin views, sidebar entries, route-guard matrix`

### Task 14: Frontend foundation — http, csrf, api client, types

**Files:**
- Create: `sm_newsletter/ui/utils/http.ts`, `ui/utils/csrf.ts` (copied from news, with
  `BASE = '/api/newsletter'`), `ui/utils/api.ts`, `ui/utils/types.ts`,
  `ui/utils/puckData.ts`
- Modify: `ui/utils/i18n.ts` (fix the `translate()` doc: the error decoder is *a* caller, per the
  PR 2 deferred item), `locales/en.json`, `de.json` (`errors.<code>` for every error code above,
  plus `errors.generic`)
- Test: `ui/utils/api.test.ts`, `ui/utils/puckData.test.ts`

**Interfaces (Produces):**
```ts
export type Block = { type: BlockType; props: Record<string, unknown> & { id: string } };
export type BlockType = 'Heading'|'RichText'|'Image'|'Button'|'Divider'|'Spacer'|'ArticleCard'|'PageCard';
export interface CampaignSummary { id: number; name: string; subject: string; status: string; list_type_key: string; updated_at: string; recipient_count: number; sent_count: number }
export interface CampaignDetail extends CampaignSummary { preheader: string; from_name: string|null; reply_to: string|null; audience: string; body: Block[] }
export const api: {
  listCampaigns(p: {q?: string; status?: string; offset?: number}): Promise<{items: CampaignSummary[]; total: number}>;
  createCampaign(b: {name: string; list_type_key: string}): Promise<CampaignDetail>;
  getCampaign(id: number): Promise<CampaignDetail>;
  patchCampaign(id: number, b: Partial<CampaignDetail> & {expected_updated_at: string}): Promise<CampaignDetail>;
  deleteCampaign(id: number): Promise<void>;
  lists(): Promise<string[]>;
  searchCards(kind: 'article'|'page', q: string): Promise<CardHit[]>;
  snapshot(kind: 'article'|'page', source_id: number): Promise<Block['props']>;
  refreshCard(id: number, block_id: string): Promise<CampaignDetail>;
  searchMedia(q: string): Promise<MediaHit[]>;
  preview(id: number): Promise<Preview>; previewUnsaved(b: {subject: string; preheader: string; body: Block[]}): Promise<Preview>;
  testSend(id: number, recipients: string[]): Promise<{results: TestSendResult[]}>;
  getSettings(): Promise<SettingsOut>; putSettings(b: Partial<SettingsOut>): Promise<SettingsOut & {password_cleared: boolean}>;
  putPassword(password: string): Promise<{has_password: boolean}>;
};
export function errorMessage(e: unknown, t: Translate): string   // maps {code} → t(keys.newsletter.errors[code]) else errors.generic
// puckData.ts
export function toPuckData(body: Block[]): Data
export function fromPuckData(data: Data): Block[]
```

- [ ] **Step 1: Failing vitest.**
  - `api.test.ts`: `sends csrf header on writes`, `maps error codes to catalogue keys`.
  - `puckData.test.ts`: `round-trips content and drops root`.
- [ ] **Step 2–4: Run → implement → run.** Run `npx vitest run modules/newsletter/sm_newsletter/ui/utils`,
  then tsc and check_locales. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): frontend API client and Puck data mapping`

### Task 15: Campaigns list page

**Files:**
- Create: `sm_newsletter/pages/Campaigns.tsx`, `ui/components/campaigns/CampaignTable.tsx`,
  `ui/components/campaigns/NewCampaignDialog.tsx`, `ui/hooks/useCampaignList.ts`
- Modify: `locales/en.json`, `de.json` (`campaigns.*`)
- Test: `ui/hooks/useCampaignList.test.ts`, `ui/components/campaigns/NewCampaignDialog.test.tsx`
  (`// @vitest-environment happy-dom`, as in news)

The page uses the console's `@simple-module-py/ui` components. It shows a table (name, subject,
status badge, list, updated), a search box and a status filter. The *New campaign* dialog has a
name and a list select fed by `api.lists()`. When there are no lists, it says to create a records
newsletter list first. Creating navigates to the editor with `router.visit`. Delete is offered on
drafts only, behind a confirm. It is hidden without `can_edit`.

- [ ] **Step 1: Failing tests.**
  - `useCampaignList` `debounces search and resets offset`;
  - NewCampaignDialog `disables create without a list`, `shows the no-lists note`.
- [ ] **Step 2–4: Run → implement → run.** Run vitest, tsc, `check_rules.py` (pages rule) and
  check_locales. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): campaigns list page`

### Task 16: Newsletter Puck config, blocks, pickers and the editor page

**Files:**
- Create: `ui/components/editor/puckConfig.tsx` (`buildConfig(capabilities)`),
  `editor/blocks/text.tsx` (Heading, RichText), `editor/blocks/media.tsx` (Image, Button,
  Divider, Spacer), `editor/blocks/cards.tsx` (ArticleCard, PageCard), `editor/CardPicker.tsx`,
  `editor/MediaField.tsx`, `editor/localizeConfig.ts` (news' pattern), `editor/CampaignMeta.tsx`
  (name, subject, preheader, from-name, reply-to), `ui/hooks/useCampaignEditor.ts`, `pages/CampaignEditor.tsx`
- Modify: `locales/en.json`, `de.json` (`editor.*`, `blocks.*`)
- Test: `editor/puckConfig.test.ts`, `ui/hooks/useCampaignEditor.test.ts`, `editor/localizeConfig.test.ts`

**Interfaces:**
```ts
export function buildConfig(caps: {news: boolean; pagebuilder: boolean}): Config   // categories: content (Heading, RichText, Image, Button), layout (Divider, Spacer), cards (ArticleCard, PageCard; visible: caps.news || caps.pagebuilder); root.render wraps children in a 600px single column
export function useCampaignEditor(id: number): { campaign: CampaignDetail | null; data: Data; onChange(d: Data): void; saveMeta(p: Partial<CampaignDetail>): void; status: 'idle'|'saving'|'saved'|'stale'|'error'; refresh(blockId: string): Promise<void> }
```
- Block field rules: the same names and limits as Task 4. RichText uses Puck's `richtext` field.
  Image `src` is a custom `MediaField`: a URL input plus *Choose from media* when
  `caps.pagebuilder`.
- A card block's field is a custom `CardPicker`. It searches, and selecting calls `api.snapshot`
  and replaces the props. It carries a *Refresh* button calling `refresh(blockId)`. When the
  capability is off, both are disabled with `editor.integration_missing`.
- Block `render`s approximate the email (600 px, inline styles). The real preview is Task 17.
- No DropZones or slots, so the layout stays single-column.
- Autosave is debounced 1.5 s and sends `expected_updated_at`. A 409 `stale` sets status `stale`
  and shows a reload banner. When the user is without `can_edit`, Puck is read-only
  (`permissions: {drag: false, edit: false, insert: false, delete: false, duplicate: false}`).

- [ ] **Step 1: Failing tests.**
  - `puckConfig.test.ts`:
    - `defines all eight blocks always`;
    - `hides the cards category when neither integration is available`;
    - `ArticleCard insertable only with news`: the cards category lists ArticleCard only when
      `news` and PageCard only when `pagebuilder`;
    - `no slot or dropzone fields`.
  - `useCampaignEditor.test.ts`:
    - `debounces saves`;
    - `sends expected_updated_at and adopts the response's`;
    - `stale stops autosave`.
  - `localizeConfig.test.ts`: `resolves labels to strings`.
- [ ] **Step 2–4: Run → implement → run.** Run vitest, tsc, file-size check (split blocks files
  if near 280), check_locales. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): newsletter-only Puck editor with card and media pickers`

### Task 17: Preview pane and test-send dialog

**Files:**
- Create: `ui/components/editor/PreviewPane.tsx`, `ui/components/editor/TestSendDialog.tsx`,
  `ui/hooks/usePreview.ts`
- Modify: `pages/CampaignEditor.tsx` (Edit / Preview tabs, *Send test* button when `can_send`),
  `locales/en.json`, `de.json` (`preview.*`, `test_send.*`)
- Test: `ui/hooks/usePreview.test.ts`, `ui/components/editor/TestSendDialog.test.tsx`

- **PreviewPane** has HTML and Plain-text tabs.
  - HTML renders in `<iframe sandbox="" srcDoc={html} title=…>` at 600 px plus a mobile 375 px
    toggle.
  - Plain text renders in a `<pre>`.
  - Warnings show as translated notes (`preview.warning.<code>`).
  - It fetches `previewUnsaved` with the current editor data (debounced 500 ms).
- **TestSendDialog** takes up to `max_test_recipients` addresses (comma or newline separated,
  counted after trim and dedupe) and shows the per-address outcome. A 429 shows
  `errors.send_budget_exhausted`, and a 422 shows the named field.

- [ ] **Step 1: Failing tests.**
  - `usePreview`: `uses the unsaved body`.
  - TestSendDialog:
    - `refuses a sixth address client-side`;
    - `shows per-recipient results`;
    - `iframe is sandboxed with no tokens`: PreviewPane's iframe `sandbox` attribute is `""`.
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): preview pane and test-send dialog`

### Task 18: Settings page

**Files:**
- Create: `sm_newsletter/pages/Settings.tsx`, `ui/components/settings/SettingsForm.tsx`,
  `ui/components/settings/PasswordField.tsx`
- Modify: `locales/en.json`, `de.json` (`settings.*`)
- Test: `ui/components/settings/SettingsForm.test.tsx`

The form is grouped as Transport (transport, host, port, security, username, password), Sender
(from address, from name, reply-to, physical address), Limits (daily, per minute) and Tracking
(opens, clicks: marked "applies from PR 5", wording `settings.tracking_note`).
- The password field is write-only. It shows "saved" when `has_password` and sends through
  `putPassword`. It never pre-fills.
- Changing any server field shows `settings.server_change_clears_password` before Save. After a
  save with `password_cleared`, the page shows the notice.
- Without `can_write`, the form is read-only with `settings.read_only_note`.

- [ ] **Step 1: Failing tests.**
  - `warns before a server change`;
  - `never renders the password value`;
  - `read-only without can_write`.
- [ ] **Step 2–4: Run → implement → run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(newsletter): newsletter settings page`

### Task 19: Docs, wiring and branch verification

**Files:**
- Modify:
  - `modules/newsletter/docs/index.md` (status table: PR 2 merged, PR 3 this; a new "Campaigns
    and content" section covering blocks, sanitising, cards, preview, test send and the budget;
    Settings: the page, R10);
  - `modules/newsletter/README.md`;
  - `CLAUDE.md` (one short paragraph on newsletter content, below);
  - `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md` (PR 3 row → this plan; PR 4 must
    answer `/newsletter/u/test` like a forged token, R1).
- Modify: `host/tests/test_newsletter_wiring.py` (add `test_views_and_menu_mounted`: the three
  view paths and two menu URLs are on the built host app).
- Create: `modules/newsletter/docs/content.md` (blocks, merge fields, footer, the URL rules, the
  goldens and how to update them).

**The CLAUDE.md paragraph** says four things:
1. Newsletter email HTML is produced only by `sm_newsletter.content.render`.
2. Rich text is re-serialised from an allow-list at save and at render.
3. Card and media lookups go through `news.contracts.articles` and `pagebuilder.contracts.cards` only.
4. A settings write that changes the SMTP server clears the stored password.

- [ ] **Step 1: Write the docs and the host test.**
- [ ] **Step 2: Verify.**
  - Run the host test: `uv run --directory host pytest tests/test_newsletter_wiring.py -q -p no:cacheprovider`.
  - Run `make gen-pages`, then `uv run python scripts/check_rules.py`, `check_locales.py`,
    `check_file_size.py`, `check_hardcoded_strings.py`, `check_readmes.py` and `uv run ruff check modules/newsletter modules/pagebuilder/pagebuilder/contracts modules/records/sm_records/contracts`.
  - Run `npx biome check modules/newsletter` and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`.
  - Expected: all pass.
- [ ] **Step 3: Migration check.** No model changes in this PR. Confirm with
  `uv run alembic -c host/alembic.ini check` on SQLite ("No new upgrade operations detected").
- [ ] **Step 4: Commit.** `docs(newsletter): campaigns and content (PR 3)`

---

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| Campaign CRUD, draft only | 7 |
| Blocks: heading, rich text, image, button, divider, spacer, article and page cards; validation | 4, 5 |
| Cards snapshotted at insert, Refresh, contracts only | 3, 8 |
| Table-based inline HTML and text, fixed footer with address and unsubscribe, merge fields | 4, 6 |
| Branding from the framework module | 6 (R7) |
| Puck editor, newsletter-only config, 600 px single column; list, editor and preview pages | 15, 16, 17 |
| Preview = server render in an iframe | 9, 17 |
| Test send ≤5, `[TEST]`, counts against the cap (amendment 4 ledger) | 11 |
| Transport seam: SMTP via aiosmtplib with List-Unsubscribe; console with capture | 10, 12 |
| `/admin/newsletter/settings` page (PR 2's manage_url) | 12, 13, 18 |
| Sidebar menu, permissions and tenant binding on every route, CSRF | 13 |
| `news`/`pagebuilder` extras with floors | 1 |
| en/de locales | 6, 13–18 |
| PR 2 deferred items: Important 1 → R10; `translate()` doc; `-test-support.tsx` exclude | 12, 14, 1 |

## Amendments from the Codex plan review (2026-11-03)

These override any task or ruling above that contradicts them.

1. **R11 replaced: test sends go through the one dispatcher lock.** A test send takes PR 2's global
   dispatch lock (Postgres advisory lock; the `newsletter_dispatch_lock` row on SQLite — spec
   amendment 4) for admission *and* the SMTP calls. Inside the lock: count the rolling 24 h and
   60 s windows from `newsletter_send_attempt` across all tenants, write one attempt row per
   recipient immediately before its SMTP call, resolve it after. An attempt row that never
   resolves (crash) stays counted for its window — conservative. Over budget → 429
   `send_budget_exhausted`, nothing sent. Test: two concurrent test sends with a fake clock and a
   cap of 3 never exceed 3 attempts. PR 4's dispatcher uses the same admission helper.
2. **R15 replaced: an integer `revision` column.** A new alembic revision (off the current head,
   no branch label) adds `newsletter_campaign.revision INTEGER NOT NULL DEFAULT 1`. PATCH and
   Refresh both require `expected_revision`; the write is one conditional
   `UPDATE … SET revision = revision + 1 WHERE id = :id AND tenant_id = :t AND status = 'draft' AND revision = :r`;
   zero rows → 409 `stale` (or `not_a_draft` after re-reading status). The editor flushes pending
   autosave before Refresh. Tests: concurrent PATCH/PATCH and PATCH/Refresh, exactly one wins.
   This also removes the nullable `updated_at` problem.
3. **Every campaign request checks list access.** One helper (`campaigns/access.py`) runs
   `can_read_list` for the campaign's `list_type_key` on every read, list (filter out campaigns on
   lists the caller cannot read), preview, card/refresh and test send — not only when the list is
   chosen. Test: restrict the list's `allowed_roles` after creating a campaign → its read, preview
   and test send are 403/404 for that caller.
4. **SMTP envelope recovery.** After any MAIL/RCPT/DATA rejection the transport issues `RSET`
   (as `aiosmtplib.sendmail` does) before the next recipient; a disconnect or timeout before DATA
   is a pre-acceptance failure (reconnect, retryable); after the body was sent it is
   *outcome unknown* (spec amendment 2). Tests on aiosmtpd: first recipient rejected, second
   accepted; disconnect at RCPT then recovery.
5. **All header inputs validated before admission.** Settings `from_name`, `from_address`,
   `reply_to` and campaign subject/from-name/reply-to reject CR/LF and control characters at their
   write (422, no echo) and are re-checked before the ledger admits an attempt. Settings-level
   CR/LF tests.
6. **R6 amended: a per-tenant public origin.** Content links (article and page cards, images) are
   made absolute against the *campaign tenant's* public origin: on a multi-tenant host with
   `tenants.subdomain_base`, the framework's canonical origin for that organisation (find the
   framework helper; if none, `<scheme of public_base_url>://<org slug>.<subdomain_base>`), else
   `public_base_url`. Never the request Host. Test: identical slugs in two tenants render two
   different absolute URLs. Newsletter's own public routes (unsubscribe, later tracking) keep
   `public_base_url`, since their tenant comes from the token.
7. **R7 amended: the logo is served platform-scoped.** The email's logo URL is a newsletter public
   route (`/newsletter/brand/logo`) that serves the SYSTEM-scope branding logo explicitly, never
   the requesting tenant's override; no logo when branding has none. Test with a tenant override
   present: the route still serves the system logo, anonymously.
8. **Puck palette:** unavailable card components go into a hidden category and `other` is
   `visible: false`. Test the palette with news absent, pagebuilder absent, both absent.
9. **Viewers preview the saved campaign** with the GET preview; the unsaved POST preview is used
   only for editable drafts by `newsletter.edit` holders. Test the viewer flow.
10. **Route-guard test** walks effective routes with `iter_route_contexts(app.routes)` (as the
    other modules' tests do), asserts the expected newsletter route set is non-empty and complete,
    and asserts `bind_admin` and the permission are present on each (order: match PR 2's actual
    router — CSRF outer is fine; rule and document it).
11. **Sanitiser output escaping.** Every emitted attribute value is
    `html.escape(value, quote=True)` after the scheme check (performed on the decoded,
    whitespace/control-stripped, lowercased value). Tests: entity-encoded quotes and
    `javascript:`/`data:`/`vbscript:` schemes (`&#106;avascript:`, `java\tscript:`), duplicate
    `href`, comments, malformed nesting, `<script>` inside allowed tags, `<style>`, `<svg>`.
12. **Drop `get_media_card`** from the pagebuilder contract; the picker uses the media search only.
