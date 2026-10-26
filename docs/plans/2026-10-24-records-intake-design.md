# Design: a working contact form and newsletter, built into records (#101)

> **Implemented in #101 over four PRs (#232, #244, #251 and the block,
> retention and CAPTCHA PR).** In code, "intake" is "public submissions":
> `records_type.public_submissions`, `sm_records/public_submissions/`,
> `/api/records/submissions/`, `/records/submissions/`, the
> `public_submissions_*` settings and the `records.public_submissions.*`
> strings. Each PR's description lists its deviations from this document.

Status: proposal, for one approval. It replaces the `modules/forms` design
(`design-101.md`), which the user rejected with "Extend records to support
everything we need." There is **no new package**: `modules/records`
(`sm_records`) provides both the contact form and the newsletter.

Verified against `origin/main` @ `d2e0342` (framework 0.0.38). The framework
APIs this design relies on were checked in the installed 0.0.38 packages:
`EventBus.durable_transport` / `publish_durable` (`simple_module_core/events.py`),
`simple_module_core.mail` (`MailMessage`, `current_mail_sender`,
`mail_transport_installed`), `simple_module_core.leases.lease`,
`app.state.sm.rate_limit_store` (`services.py`), the host `secret_key` and
`public_base_url`. Records files cited are on `main`. Line counts that matter
for the 300-line cap are given where a file is close to it.

The abuse layers, the CSRF reasoning, privacy, the mail path and the
newsletter flow from `design-101.md` carry over. This document restates them
in full where they change, and says "as in `design-101.md` §N" only where they
carry over word for word.

---

## 1. Goal and scope

**Goal.** A site built with pagebuilder can put a working contact form and a
working newsletter signup on a published page (or in the site header/footer).
The data lands in records, and admins handle it with the records screens they
already have.

1. **Public submissions (a "form type").** A record type opts in to anonymous
   submissions. A new pagebuilder block, **`RecordForm`**, registered from
   `sm_records/pagebuilder-blocks.ts`, renders its inputs from that type's
   schema. An anonymous endpoint validates the submission against the schema,
   through the existing record services, and stores it as an ordinary record.
   Records adds system fields (source page and block, IP hash, user agent,
   spam reason, notified-at). Admins can see them but cannot edit them. One
   or more recipients get an email for each submission.
2. **Newsletter (a "subscription type").** A record type of the second
   *intake kind*. Its system-managed fields hold the email, the status
   (pending / confirmed / unsubscribed), the consent proof and a nonce. The
   email is unique within the type (so unique per tenant). The double opt-in
   flow lives in records: a confirmation email, POST-button confirm and
   unsubscribe pages, a stateless HMAC unsubscribe link, and identical replies
   that let nobody enumerate addresses. The same `RecordForm` block renders
   it.
3. **Admins** use records' existing list, filters, columns, record editor,
   revisions, CSV/JSON export, bulk actions, trash and purge. Records adds a
   few actions on top: *Resend notification*, *Resend confirmation*, *Mark as
   spam*, *Not spam* and *Unsubscribe*.

**Out of scope (v1):**
- Sending newsletters or campaigns, bounce or complaint processing, and sync
  to Mailchimp and similar services. The events make these possible later.
- Full-text search over submission bodies. Records filters only indexed
  fields, so you can filter on email, enquiry and triage, but not on message
  text.
- File attachments. `media` fields are never publicly submittable.
- Relation, json and media fields on a public form.
- A copy of the message to the submitter (a mail-bombing vector).
- `List-Unsubscribe` headers (`MailMessage` cannot carry headers; Q5).
- Spam scoring services such as Akismet.
- Making pagebuilder's existing `ContactForm`/`Newsletter` blocks submit
  (Q2).
- One-step GDPR erasure across types. Erasure is a per-type filter plus bulk
  purge (§9).
- Importing subscribers with their consent proof (Q7).

---

## 2. The core decision: an "intake" capability on record types

A record type gains an optional **intake** config: one nullable JSON column,
`records_type.intake`. Its `kind` is either `"form"` or `"subscription"`.
With no config the type behaves exactly as it does today, so the feature is
inert on every existing type and every existing host.

### 2.1 Generic capability vs a built-in system type (for the newsletter)

**Decision: the newsletter is a generic capability (`kind: "subscription"`)
that any type can take, not a built-in system type.**

| | Built-in system type (seeded `newsletter`) | Generic `subscription` kind (chosen) |
|---|---|---|
| Per-tenant creation | Records would have to seed a type in every tenant. Tenants are created at runtime, and records has no hook for that and must not depend on `tenants` | The admin creates it, like any other type, from the *Newsletter list* preset |
| Several lists per tenant | Needs a second mechanism | Free: one type per list (e.g. `newsletter_en`, `product_updates`) |
| Key and permissions | A reserved key that collides with whatever a host already called `newsletter` | An ordinary key, `allowed_roles`, sidebar entry and collection |
| Extra fields (first name, interests) | Needs a schema-extension story for a system type | Ordinary fields beside the system ones |
| Code paths | A special type through every service | The same intake path as forms: one capability, two field specs and two flows |
| Risk | The schema is fixed, so it is "correct by construction" | An admin could build an odd list. The system fields are locked and injected by the server (§3.2), so the parts the flow depends on cannot be broken |

The same reasoning makes the contact form a `kind: "form"` type rather than
a fixed `contact` type. The admin picks the fields: the preset gives name,
email, enquiry, message and triage, and the admin can change them.

### 2.2 What is reused and what is new

| Need | Reused from records as-is | New |
|---|---|---|
| Storage, validation, revisions, unique email | `services.records.create_record`/`update_record`, `_prepare` (validate, lock, `ensure_unique`), `write_revision`, `write_index` | An internal `system=` argument on both, which merges server-written system values after validation (like `orphaned_extra`) |
| Schema of the form | `RecordType.fields`, `schema/fields.py` `validate_fields`, the compiled validator | `FieldDefinition.system` flag, the `sm_` key reservation, the canonical system field specs (`intake/spec.py`) |
| Admin list, search, columns | `RecordList` page, `FilterBar`, `ColumnChooser`, the index tables (filter `sm_status:eq:confirmed`, `email:eq:…`) | None |
| Detail | `RecordEditor`, `RecordRevisions` | System fields render read-only in an `IntakeDetails` panel. Intake action buttons |
| Export | `services/export.py` (CSV with formula escaping, JSON, streamed) | `internal` system fields left out of the export |
| Spam folder | **The trash.** Soft delete, restore, empty trash, purge, `RecordTrashed`/`RecordRestored` | `Mark as spam` (system write `sm_spam`, then trash) and `Not spam` (restore, clear, notify) |
| Retention and erasure | `hard_delete_record`, bulk purge, empty trash | A purge loop for `retention_days` and `pending_purge_days` |
| Per-type access to PII | `allowed_roles` + `check_type_roles` on every read and write | A type-editor warning when an intake type has no `allowed_roles` |
| Tenancy | `tenancy.bind_public`/`bind_admin`/`tenant_scope`, the guard, the census, the isolation matrix | Confirm/unsubscribe bind the tenant named in the signed link (§4.4) |
| Anonymous surface | `boot.py` mount-and-exempt pattern, `PublicErrorRoute`, `_body_limit` | A second router, under the fixed prefix `/api/records/intake/`, exempted for `GET`+`POST` |
| Events | `events.emit` (after commit, per tenant), `contracts/events.py` | `FormSubmitted`, `SubscriptionChanged` |
| Pagebuilder | `pagebuilder-blocks.ts` + `registerPuckBlocks` (optional peer), the `RecordsList` editor patterns (`resolveFields`, `englishText`) | The `RecordForm` block (`layout: true`) |
| Settings | `RecordsSettings` (DB-backed, no env) | `settings_intake.py` mixin, host-wide abuse knobs |
| i18n | `locales/en.json`/`de.json`, `utils/i18n.ts` | A `records.intake.*` key tree and the mail strings |
| Mail | none (records sends no mail today) | `intake/mail.py`: outbox when present, otherwise after commit |
| Permissions | `records.view` / `records.edit` / `records.manage_types` | **none new** |

Things this deletes from the forms design: the new package (pyproject, entry
point, module class, PyPI publisher, README and docs skeleton, host wiring);
two tables; three permissions; three admin pages; the CSV exporter; the
erasure endpoint; the menu items; the pagebuilder submission seam
(`formSubmit.ts`, `PublicFormProvider`, `useBlockForm`, the contact-form
splits); and the `find_published_block` pagebuilder contract.

### 2.3 The trust anchor moves from the block to the type

`design-101.md` validated a submission against the *published block's* props,
which needed a new pagebuilder contract. Records cannot do that: pagebuilder
is only an **optional peer** of records, both in npm and as the `pagebuilder`
Python extra, and records must never import it. So the **record type is the
authority**:
- which fields can be submitted (`intake.public_fields`)
- their validation (the schema)
- the consent text (`intake.consent`)
- the recipients (`intake.notify_to`)

The block only names a type key and adds presentation, such as label
overrides and success copy. Nothing the server trusts lives in block props,
which ship to every visitor inside the page JSON.

Trade-off: records cannot prove a submission came from a specific published
block. `sm_source_block` is a client-supplied hint (≤100 characters) and
`sm_source_page` is the server-observed `Referer` path. The per-block
throttle becomes a **per-type** throttle, because a block id the client
names cannot key a limit.

---

## 3. Data model and the host migration

### 3.1 `records_type.intake`

`sm_records/models/_type.py`: one new column.

```python
intake: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
"""Public-intake config (``sm_records.intake.spec.IntakeConfig``), or ``None``.
Operational like ``is_public``: not snapshotted in ``records_type_revision``,
bumps no ``schema_version``."""
```

The config shape is validated by `sm_records/contracts/intake.py::IntakeConfig`
(plain `SQLModel`, per the contracts rule):

| Key | Type / default | Meaning |
|---|---|---|
| `kind` | `"form" \| "subscription"` | Set once (null → kind). Clearing or changing it is a 409 (§3.4) |
| `enabled` | `bool = False` | Whether the public endpoints accept submissions. Off answers the shared 404 |
| `public_fields` | `list[str] = []` | **Allowlist** of non-system field keys a visitor may fill, in render order. Only `text, longtext, email, url, number, integer, boolean, date, datetime, select, multiselect` |
| `notify_to` | `list[EmailStr]`, ≤10, `[]` | Form kind: who gets the notification. Empty means stored and not sent, and the list screen shows a banner |
| `consent` | `{required: bool=False, text: {locale: str}}` | A checkbox the visitor must tick when `required`. Its text in the visitor's locale is snapshotted into `sm_consent_text`. Required for `subscription` when `double_opt_in` is off |
| `double_opt_in` | `bool = True` | Subscription kind only. Off: signup goes straight to `confirmed`, which is not recommended under GDPR/UWG in DE |
| `retention_days` | `int ≥ 0 = 365` | Form kind: records older than this are purged. `0` keeps them forever |
| `pending_purge_days` | `int ≥ 1 = 30` | Subscription kind: never-confirmed records are purged after this |

Recipients live on the type, not in a tenant-overridable setting as
`design-101.md` §6 had them. Types are already per tenant, so this gives
per-tenant **and** per-form routing for free. `design-101.md` Q3 goes away.
`GET /types/{key}` exposes `notify_to` to `records.view` holders, who are
staff. That is acceptable, and the README says so.

### 3.2 System fields

**`FieldDefinition.system: Literal["readonly", "internal"] | None = None`**
(`schema/fields.py`, 274 lines; the field adds about 4 lines, and the
validation goes to `intake/spec.py`).

- **Key namespace.** Every system key starts with `sm_`. `schema/_keys.py`
  `validate_key(on_save=True)` refuses a non-system field whose key starts
  with `sm_` ("reserved for system fields"). The check is save-only, like
  the virtual-key rule, so a type stored before this rule still loads.
  `components/typeeditor/rules.ts` mirrors the rule.
- **Injected, never trusted.** `services._schema.normalise`, the one path
  every type create, update, rollback and type import goes through, strips
  every inbound entry with `system` set. It then appends the canonical
  definitions for `intake.kind` from `intake/spec.py`. A client therefore
  cannot add, retype, relabel, make optional or remove a system field. A
  rollback to a pre-intake revision still ends up with the system fields.
  The diff therefore never sees a system field change, except an *additive*
  one when a type first gains a kind.
- **Who writes them.** Only records' intake services, through the internal
  `system=` argument on `create_record`/`update_record`.
  `services/_payload.carry_system(defs, data, previous)` runs before
  validation on every write:
  - **update:** the stored system values replace whatever the client sent.
    The editor echoes the record back, so this is a carry, not a 422.
  - **create** (admin or import): system keys are dropped.
  Then `system=` is merged into the validated values. So no admin write,
  import or bulk action can change a system value, and an echoed value is
  never an error.
- **`readonly`** fields show in the editor's `IntakeDetails` panel, in the
  list's column chooser and in export. **`internal`** fields (only
  `sm_nonce`) are hidden from the editor, the columns and export, and stay in
  the admin API's `data`. They are not secret on their own: every link built
  from them also needs `secret_key`.

Canonical specs (`sm_records/intake/spec.py`):

**`kind: "form"`**

| Key | Type | System | Notes |
|---|---|---|---|
| `sm_source_page` | text (max 300) | readonly | `Referer` path, server-observed. Null when absent |
| `sm_source_block` | text (max 100) | readonly | Client hint, the Puck `props.id` |
| `sm_locale` | text (max 16) | readonly | The page language the block reports, if it matches `LOCALE_PATTERN` |
| `sm_ip_hash` | text (max 64) | readonly | `HMAC(secret_key, tenant\|ip)` hex. Null if `intake_store_ip_hash` is off |
| `sm_user_agent` | text (max 256) | readonly | Truncated. Null if `intake_store_user_agent` is off |
| `sm_consent_text` | longtext | readonly | Snapshot when `consent.required` |
| `sm_spam` | select `links\|manual` | readonly | Why it is in the trash |
| `sm_notified_at` | datetime | readonly | Null means "not sent", which the list and editor show |

**`kind: "subscription"`**

| Key | Type | System | Notes |
|---|---|---|---|
| `sm_email` | email, required, **unique**, indexed | readonly | Normalised `strip().lower()` before validation. It is the type's `display_field` |
| `sm_status` | select `pending\|confirmed\|unsubscribed`, indexed | readonly | Filterable in `FilterBar` |
| `sm_locale` | text (max 16) | readonly | Language of the confirmation mail |
| `sm_source_page` | text (max 300) | readonly | |
| `sm_consent_text` | longtext | readonly | Consent proof |
| `sm_consent_at`, `sm_confirmed_at`, `sm_unsubscribed_at`, `sm_confirm_sent_at` | datetime | readonly | |
| `sm_consent_ip_hash` | text (max 64) | readonly | |
| `sm_nonce` | text (max 32) | **internal** | `secrets.token_hex(16)`. Rotated on re-subscribe and on admin unsubscribe, which kills old links |

Indexed system fields count against `max_indexed_fields_per_type` (25):
the subscription kind uses 2 and the form kind 0. "Unique per tenant within
that type" is records' existing `unique` claim (`_claims.ensure_unique`):
types are per tenant, and the type row lock serialises the check.

Ordinary fields come from **presets**, in `utils/intake-presets.ts`. They are
offered by *New type → From a preset* and are plain fields the admin can
change:
- **Contact form:** `name` (text, required, max 200), `email` (email,
  required, indexed), `enquiry` (select, optional), `message` (longtext,
  required, max 5000), and `triage` (select `new|in_progress|done`, default
  `new`, indexed, **not** in `public_fields`, so the admin's workflow column).
  The preset also sets `display_field=name`, `show_in_menu=true` and
  `public_fields=[name,email,enquiry,message]`.
- **Newsletter list:** no ordinary fields (`sm_email` is the field), plus
  `show_in_menu=true`.

### 3.3 Invariants checked on type save

These live in `sm_records/intake/config.py::check(rtype, defs, config)` and
are called from `services/types.create_type` and `_type_update.update_type`
(both near the cap, so each gets a one-line call). Each refusal is a 422
naming the problem:

1. Every `public_fields` key exists, is not a system field and is of a
   submittable type.
2. While `enabled`, every **required** non-system field that has no
   `default` is in `public_fields`. Otherwise every submission would be a
   422.
3. `is_public` and `intake` are mutually exclusive. The anonymous read API
   would otherwise publish submissions, which are PII (409). Submissions are
   also always written as `draft`, a second guard.
4. `subscription`: `double_opt_in=false` requires `consent.required=true`.
5. `consent.text` keys are valid locales, each at most 2,000 characters.
6. `kind` cannot be cleared or changed once set (409). Turning a form into a
   plain type would leave system fields nobody writes. Deleting the type is
   the way out.

Removing a field (a destructive change) also removes it from `public_fields`
in the same write, so a live form never names a field that does not exist.

### 3.4 Migration

One additive revision: `host/migrations/versions/<rev>_records_type_intake.py`.
It is autogenerated from the repo root
(`uv run --project host alembic -c host/alembic.ini revision --autogenerate -m "records type intake"`),
with `down_revision` = the head at implementation time. It contains
`op.add_column("records_type", sa.Column("intake", sa.JSON(), nullable=True))`
and the matching drop. It has **no `branch_labels`**: it is not a module's
first revision, and the CLAUDE.md caveat applies in any case. There is no
backfill: null means "not an intake type".

No record-table change. System fields live in the payload and the existing
index tables, so a declared collection needs no DDL either.

---

## 4. API and routes

### 4.1 Public (anonymous) intake API

The router is `sm_records/endpoints/api/intake_public.py`, at the **fixed**
prefix `constants.INTAKE_API_PREFIX = "/api/records/intake/"`. It is mounted
and exempted from `boot.py` beside the read API, using the same
`dir_prefix`/idempotent `add_prefix` pattern, with
`methods={"GET", "POST"}` (`constants.INTAKE_ROUTE_METHODS`). The prefix is
fixed rather than a setting, so it needs no restart flag and no
"would this exempt the admin API" check: no admin route lives under
`/api/records/intake/`. The admin routes are `/types…` and `/revisions`.
`settings_checks.check_public_route_prefix` additionally refuses a
`public_route_prefix` equal to or under the intake prefix, so the read API's
`GET`-only exemption can never overlap it.

Route class: `IntakeErrorRoute(PublicErrorRoute)`. It keeps `error_headers`
and adds a stable snake_case `code` to each refusal. Dependencies, in order:
`bind_public` (404 with no tenant), then `intake_guard` (the master switch,
content type, Origin and the body cap; §5). Every response gets
`Cache-Control: no-store`.

| Method | Path | Body / answer |
|---|---|---|
| GET | `/api/records/intake/{type_key}` | The **form definition**: `{kind, schema_version, fields: [{key,type,label,help,required,choices,constraints,default}], consent: {required, text} \| null, token, captcha: {provider, site_key} \| null}`. Only `public_fields`, with consent text in `?locale=` (falling back to the default). A type that is unknown, not intake or not `enabled` gets the shared 404. Fetched when the block mounts |
| POST | `/api/records/intake/{type_key}/submit` | `{data: {...}, token, hp, consent?: bool, block?: str, locale?: str, captcha_response?}`. Form kind: 202 `{ok: true}`. Subscription kind: **always** 202 `{ok: true}`, whatever the address's state |
| POST | `/api/records/intake/confirm` | `{t}` (JSON **or** form-encoded). pending → confirmed. 200 `{status: "confirmed" \| "already_confirmed"}`, or 410 `link_expired` |
| POST | `/api/records/intake/unsubscribe` | `{t}` (JSON or form-encoded). → unsubscribed. Idempotent, **always** 200 `{status: "unsubscribed"}`, even for an invalid link (§4.4) |

`hp` is the honeypot (§5). `data` keys outside `public_fields` are a 422
`unknown_field`. A `token.schema_version` that differs from the type's current
one is a 409 `form_changed` carrying the fresh definition (§7.3).

### 4.2 Public views (the confirm and unsubscribe landing pages)

`sm_records/endpoints/intake_views.py`, at the fixed
`constants.INTAKE_VIEW_PREFIX = "/records/intake/"`, outside `/admin/records`.
It is exempted for `GET`. One real Inertia page, `pages/IntakeAction.tsx`
(`Records/IntakeAction`):

| Method | Path | Page |
|---|---|---|
| GET | `/records/intake/confirm?t=` | **Confirm** button, then the result: confirmed / already confirmed / expired |
| GET | `/records/intake/unsubscribe?t=` | **Unsubscribe** button, then the result: unsubscribed |

The GET never changes state, because mail scanners prefetch links (as in
`design-101.md` §4). The page posts to the API. It has `BrandingHead` and
`<html lang>` set to the subscriber's `sm_locale`. The token is verified only
on POST, so the GET page answers identically for any `t`.

### 4.3 CSRF

As in `design-101.md` §4, unchanged. The public writes do **not** use
`RequiresCsrf`: anonymous pages carry no token, and the page HTML is publicly
cached. Instead, `submit` requires three things:
1. `Content-Type: application/json`, which forces a CORS preflight that no
   policy admits.
2. An `Origin` (otherwise `Referer`) that matches the request host, the host
   `public_base_url` or `intake_allowed_origins` (otherwise 403 `bad_origin`).
3. A valid signed form token (§5).

`confirm` and `unsubscribe` accept form-encoded bodies (no-JS, and RFC 8058
later) because their bearer token *is* the capability. A cross-site forger
cannot produce it.

### 4.4 Tokens (`sm_records/intake/tokens.py`)

All are HMAC-SHA256 under the host `secret_key`, base64url-encoded, and
compared in constant time.

- **Form token:** `issued.nonce.mac(tenant|type_key|schema_version|issued|nonce)`.
  Stateless. Rejected (400 `form_expired`) if younger than
  `intake_min_fill_seconds` or older than `intake_token_max_age_seconds`.
- **Confirm token:** `tenant.uuid.exp.mac("confirm"|tenant|type_key|uuid|sm_nonce|exp)`.
  `exp = now + intake_confirm_ttl_hours`. It is minted **at send time** from
  the record's current state, so nothing secret is ever stored or put in the
  outbox. This is simpler than `design-101.md`'s stored token hash: there is
  no token column, no lookup by hash and no cross-tenant query.
- **Unsubscribe token:** `tenant.uuid.mac("unsub"|tenant|type_key|uuid|sm_nonce)`.
  Stable and stateless, so a future campaign sender can build it. Rotating
  `sm_nonce` kills it.

**Tenant binding for the two link endpoints.** The link names its tenant
(`valid_tenant` checked), so a link built on the apex `public_base_url` works
in multi mode. `intake_public.bind_link_tenant` works as follows:
- If the request resolved a tenant (`tenancy._resolved`) and it differs from
  the link's, the answer is the generic refusal.
- Otherwise it enters `tenant_scope(link_tenant)` and loads the record by
  `(tenant_id, uuid)` through the existing `_by_uuid` lookup (explicit
  `tenant_id` predicate, census-clean). The MAC is checked before any
  statement runs.

A forged tenant only fails the MAC, so this is not an oracle. These two
routes are the one documented exception to "the public surface binds the
resolved tenant". It is safe because the MAC covers the tenant.

### 4.5 Admin intake actions

`sm_records/endpoints/api/intake_admin.py`, included in the admin `router`
(so `bind_admin` comes first, then `RequiresCsrf`). Every route carries
`require_edit` and `check_type_roles`, and refuses a type of the wrong kind
with 409:

| Method | Path | Kind | Effect |
|---|---|---|---|
| POST | `/api/records/types/{key}/records/{uuid}/intake/resend` | form | Re-queues the notification (throttled 1/min/record) |
| POST | same `/resend` | subscription, pending | Re-sends the confirmation, subject to `intake_confirm_rate_per_email` |
| POST | `…/intake/spam` | form | System write `sm_spam=manual`, then `soft_delete_record` |
| POST | `…/intake/not-spam` | form, trashed | `restore_record`, system write `sm_spam=null`, notification queued |
| POST | `…/intake/unsubscribe` | subscription | → `unsubscribed`, rotates `sm_nonce`, clears consent fields (§9) |

These routes register in `endpoints/api/__init__.py` **before**
`records.router`, for the path-shadowing reason that file already documents.

`TypeRead`/`TypeCreate`/`TypeUpdate` (`contracts/_types.py`, 164 lines) gain
`intake: IntakeConfig | None`. `_type_update._EDITABLE` gains `"intake"`,
classified like `is_public`: no dry run, no revision, no `schema_version`
bump. The one exception is the first `kind` set, which appends the system
fields through `normalise` as an additive schema change.

### 4.6 The submission pipeline (`sm_records/intake/submit.py`)

Every guard runs **before** `create_record` and before any statement that
writes:

1. Guards §5.1–§5.6, in order.
2. Load the type with `get_type` (tenant-scoped). Check `intake.enabled`.
3. Build `data` = the visitor's values for `public_fields` only. Fields
   outside `public_fields` that have a default get it from the validator.
4. Subscription: normalise the email, then branch to `subscribe.py` (§7).
5. Form: run the link heuristic (§5.7), then
   `create_record(db, rtype, data=data, settings=…, status=DRAFT, actor=None, system={…})`.
   This is the same call the admin `POST /records` makes, so the validation,
   `unique` claims, revision, index rows and `RecordCreated` are identical.
   A `ValidationFailed` becomes a 422 with the per-field errors, which the
   block shows inline.
6. Spam: `soft_delete_record` in the same transaction, with no
   `FormSubmitted` mail.
7. Otherwise `intake.events.form_submitted(db, rtype, record)`. It goes to
   the outbox when present, otherwise through `on_commit` (§6).

`create_record` takes the type row lock (`_claims.lock_type`). On Postgres
that is a `SELECT … FOR UPDATE` held until the request commits, so public
submissions to one type serialise. That is milliseconds per write, bounded by
the per-type throttle, and is the same lock every admin write takes. It is
accepted.

---

## 5. Abuse handling

The checks run in order, cheapest first, and each one fails closed. They
carry over from `design-101.md` §5, keyed per **type** instead of per block.
They are implemented in `sm_records/intake/abuse.py` and `captcha.py`.

0. **Master switch.** If `intake_enabled=False`, every intake route answers
   404. This is the operator's kill switch under attack.
1. **Content type, Origin and body cap.** 415, 403 and 413 respectively.
   `_body_limit.BodyLimitMiddleware` gains a tighter ceiling,
   `intake_max_body_bytes` (16 KiB), for paths under `INTAKE_API_PREFIX`,
   checked by `Content-Length` first and then while reading, as it already
   does.
2. **Per-IP rate limit.** `intake_rate_per_ip` (`"5/10minute"`), counted in
   `app.state.sm.rate_limit_store` under the key
   `records:intake:{tenant}:ip={client_ip}`. The endpoint calls
   `store.hit(key, parse_rate(setting))` itself, because `RateLimit(...)`
   fixes its rate at construction. It answers 429 with `Retry-After`. The
   definition GET has its own static backstop through `register_rate_limits`:
   `RateLimitRule("60/minute", key="ip")` on the intake prefix.
3. **Per-type throttle.** `intake_type_rate` (`"60/hour"`), key
   `records:intake:{tenant}:type={key}`. Over the limit answers 429. This
   catches rotating-IP floods (Q4).
4. **Honeypot.** `hp` comes from a visually hidden input (off-screen,
   `tabIndex=-1`, `autoComplete="off"`, `aria-hidden`). A non-empty value
   answers the identical 202, **stores nothing and sends nothing**, and logs
   the counter `records.intake.honeypot_dropped`.
5. **Signed form token and minimum fill time** (§4.4). A failure answers 400
   `form_expired`. The block fetches a fresh definition and retries once,
   automatically.
6. **Optional CAPTCHA.** `intake_captcha_provider: none | turnstile | hcaptcha`,
   verified with `httpx` (5 s timeout) before any write. 400
   `captcha_failed`, or 503 `captcha_unavailable` (fail closed). The block
   loads the widget script only when the definition names a provider. The
   operator adds the provider's host to pagebuilder's `public_csp`. Records
   logs a startup warning if the CSP does not mention it, but only when
   pagebuilder's settings are present, read through
   `app.state.pagebuilder` with `getattr`, never an import.
7. **Link heuristic (form kind).** If more than `intake_max_links` URLs (5)
   appear across the submitted text values, the submission is stored with
   `sm_spam="links"`, **trashed**, and gets no notification. The admin can
   rescue it from the trash with *Not spam*.
8. **Mail-bombing through the newsletter.** `intake_confirm_rate_per_email`
   (`"3/day"`), key `records:intake:{tenant}:{type}:email={sha256(email)}`.
   Over the limit it still answers 202 and sends nothing. A `confirmed`
   address gets no mail at all. The reply is identical in every case.

`SM_TRUSTED_PROXY` must be set behind a proxy, otherwise everyone shares one
IP bucket. `docs/operations.md` says so.

### 5.1 Settings (`sm_records/settings_intake.py`)

`settings.py` is at 267 lines, so the new fields live in a mixin class:
`IntakeSettings(BootSettings)` in `settings_intake.py`, and
`RecordsSettings(IntakeSettings)`. This is one class on one Settings screen,
still DB-backed with no env source (CLAUDE.md rule). All fields are read per
request, so none needs `_RESTART`.

| Field | Default | Notes |
|---|---|---|
| `intake_enabled` | `True` | Master switch. It is harmless when on, because nothing is accepted until a type opts in |
| `intake_rate_per_ip` | `"5/10minute"` | Validated with `parse_rate` in a `field_validator` |
| `intake_type_rate` | `"60/hour"` | |
| `intake_confirm_rate_per_email` | `"3/day"` | |
| `intake_min_fill_seconds` | `3` | `ge=0` |
| `intake_token_max_age_seconds` | `7200` | `ge=60` |
| `intake_confirm_ttl_hours` | `168` | `ge=1` |
| `intake_max_links` | `5` | `0` disables the check |
| `intake_max_body_bytes` | `16384` | `ge=1024`, and at most `max_payload_bytes` |
| `intake_allowed_origins` | `()` | Extra origins |
| `intake_store_ip_hash`, `intake_store_user_agent` | `True`, `True` | |
| `intake_captcha_provider` / `_site_key` / `_secret` | `"none"`, `""`, `""` | The secret is masked by name pattern and stored in plaintext, like the SMTP password (Q6) |

---

## 6. Mail (`sm_records/intake/mail.py`, `intake/mail_runner.py`)

The transport path is unchanged from `design-101.md` §8 and is restated
here for records:

- **Outbox when present.** If `bus.durable_transport` exists (the host
  installs `background_tasks`), `FormSubmitted` /
  `SubscriptionChanged(pending)` go through `bus.publish_durable(event, db)`
  inside the request transaction. Durable handlers
  `records.intake.send_notification` and `records.intake.send_confirmation`
  are registered in a new `RecordsModule.register_event_handlers`. They
  retry with backoff, raise when `mail_transport_installed()` is false (so
  the message is retried rather than dropped), and **never commit
  `ctx.db`**. Each handler first enters `tenant_scope(event.tenant_id)`,
  because records' guard turns an unbound ORM statement into
  `TenantUnbound`.
- **Otherwise after commit.** Records' `events.emit` mechanism queues an
  `on_commit` callback. The callback **spawns a task** and keeps a strong
  reference (as in `design-101.md`: awaiting SMTP inside `finalize_session`
  would put mail latency, and a timing side channel, on the public reply).
  The task:
  1. opens its own session from `app.state.sm.db`,
  2. binds the tenant,
  3. sends,
  4. writes the delivery mark, and
  5. finishes through `events.commit`, never a bare `commit()`.

  `services/` still never commits. `intake/mail_runner.py` is the fourth
  documented committer, beside `cli_io`, `reindex_runner` and
  `preview_runner`, and its docstring says why. A crash can lose the mail;
  the mark then stays null, the list shows "not sent", and *Resend* recovers
  it. The demo host has no `background_tasks`, so it uses this path.
- **Preconditions.** Mail is sent only when
  `current_mail_sender().delivers_email` is true and `public_base_url` is
  set, because links must be absolute. Otherwise records logs a warning, the
  record stands, and the mark stays null.
- **Delivery marks** are system writes through
  `intake.system.system_update(db, rtype, record, {...})`. That is
  `update_record` with `expected_version=record.version` and `system=…`,
  inside `events.muted()`, so a mark is not announced as a content edit. A
  version conflict with a concurrent admin edit reloads and retries once.
  Each mark writes a revision, which is accepted: one extra row per
  submission, pruned by `revision_limit`.

**Messages.** Plain-text `string.Template` files in
`sm_records/intake/mail/` (`notify.txt`, `confirm.txt`), with the strings
from records' catalogue through a server-side `Translator` in `sm_locale`.
That is the visitor's page language if the catalogue has it, otherwise the
i18n default.

| Message | To | Content |
|---|---|---|
| Notification | `intake.notify_to` | Subject `records.intake.mail.notify.subject` ("New {type} submission on {site}"). Every public field as `label: value`, using the type's labels in the default locale, plus a link to `/admin/records/{type}/{uuid}`. No `Reply-To` (Q5) |
| Confirmation | the subscriber | The confirm link and its expiry, the unsubscribe link, and "you received this because…" |

Events (`sm_records/contracts/events.py` gains two dataclasses, and
`intake/events.py` holds their builders; `events.py` is at 295 lines and
does not grow). They carry **identifiers only**:
- `FormSubmitted(type_key, tenant_id, uuid, spam)`
- `SubscriptionChanged(type_key, tenant_id, uuid, status_before, status_after)`

`RecordCreated` fires as well, because the write is an ordinary create.

---

## 7. The newsletter (`sm_records/intake/subscribe.py`)

### 7.1 Signup

The address is normalised, then looked up with one `exists`-shaped query on
the `sm_email` index (`taken_by`-style, explicit `tenant_id`), **including
the trash**:

| Current state | What happens | Mail |
|---|---|---|
| none | `create_record` with `sm_status=pending` (or `confirmed` when `double_opt_in` is off), consent snapshot, fresh `sm_nonce` | Confirmation, subject to the per-email throttle |
| pending | No write | Confirmation re-sent, throttled |
| confirmed | No-op | **None** |
| unsubscribed | → pending, new consent snapshot, **rotated** `sm_nonce` (old unsubscribe links die) | Confirmation (reactivate) |
| trashed (an admin deleted it) | `restore_record`, → pending, new consent and nonce | Confirmation |

Every branch answers the identical 202 `{ok:true}`. Response timing is not
equalised beyond the fact that mail is never sent in the request. The
remaining difference is one write versus none, about a millisecond, and the
rate limits bound probing. That is accepted, as in `design-101.md`.

A concurrent double signup of one address loses the `ensure_unique` race
under the type lock. The loser's `Conflict` is caught and answered with the
same 202.

### 7.2 Confirm and unsubscribe

- **Confirm** (POST, token §4.4): MAC → bind tenant → load → `exp` check (410
  `link_expired`, and the page offers "subscribe again") → pending becomes
  confirmed (`sm_confirmed_at`, system write, `SubscriptionChanged`). A
  record that is already confirmed answers `already_confirmed`. An
  unsubscribed record, or a nonce mismatch, answers 410 as well: the link
  belonged to an earlier subscription.
- **Unsubscribe** (POST): MAC → bind → load → `unsubscribed`
  (`sm_unsubscribed_at`, nonce rotated, consent fields nulled per §9). It is
  idempotent. **Any** failure (bad MAC, unknown record, wrong tenant) also
  answers 200 `{status:"unsubscribed"}`, so the endpoint is no oracle and a
  user who clicks twice sees the same thing.

### 7.3 When the schema behind a live form changes

- The block fetches the definition **live** on every mount, never from the
  publicly cached page JSON. A field ticked into `public_fields` appears on
  the next page view, and an edited label shows immediately.
- The form token carries `schema_version`. A visitor who loaded the form
  before an edit and submits after it gets 409 `form_changed` with the new
  definition. The block re-renders, keeps the values of every key that still
  exists, and asks the visitor to check and send again.
- **Removing** a field drops it from `public_fields` in the same write
  (§3.3). **Adding a required field** that is not public and has no default
  is refused while `enabled` (§3.3 rule 2). **Retyping** a public field to a
  type that cannot be submitted is refused while it is in `public_fields`.
- Records the type already holds follow records' normal rules: lazy
  migration, `invalid_since` marks and the `_orphaned` undo (architecture
  "How a schema change is classified"). Nothing about intake changes them.
- Disabling the type (`enabled=false`) or deleting it makes the definition
  the shared 404. The block shows its *unavailable* state.

---

## 8. The `RecordForm` block (frontend)

Registration, in `sm_records/pagebuilder-blocks.ts`: a second
`registerPuckBlocks` call, `{ blocks: { RecordForm }, category: { key: 'forms', title: keys.records.intake.palette_group }, layout: true }`.
`layout: true` matters because the newsletter in the footer is the classic
case. The `RecordsList` registration stays page-only.

Files (each under 300 lines; nothing new under `pages/` except
`IntakeAction.tsx`):
- `components/intake/RecordFormBlock.tsx` is the Puck config, built the way
  `RecordsListBlock.tsx` is: `resolveFields`/`resolveData` in the editor
  only, `englishText` for the module-scope shape, `hiddenField`.
  - **Props:** `typeKey` (a select of intake-enabled types, from the admin
    `GET /api/records/types`), `title`, `intro`, `submitLabel`,
    `successTitle`, `successBody`, and `labels: {key: {label?, help?}}`
    (per-page overrides; the page's language is fixed, so overrides are how
    a German page gets German labels on an English-labelled type).
  - **Hidden:** `kindHint`.
- `components/intake/RecordFormRender.tsx` is the render. It fetches the
  definition, renders the inputs, the consent checkbox with server text,
  the honeypot, and the success, error and unavailable states. It reports
  `document.documentElement.lang` as `locale`.
- `components/intake/IntakeInput.tsx` is one input per submittable field
  type, built from `@simple-module-py/ui` primitives. The admin
  `components/fields/*` editors are **not** reused: they assume a session
  (the relation and media pickers) and admin chrome.
- `hooks/useIntakeForm.ts` is the state machine
  `loading → ready → submitting → success | error(code)`. It retries once on
  `form_expired`, re-renders on `form_changed`, maps 422 per-field errors
  inline, and translates 429/`captcha_failed`/network failures.
- `utils/intake-api.ts` is the fetch client: `credentials: 'same-origin'`,
  JSON, and the fixed `INTAKE_API_PREFIX`.
- **In the Puck editor** (`puck.isEditing`), the block renders the live
  definition with a disabled submit and the note "Submits on the published
  page". With no type chosen, it shows a placeholder.

**When pagebuilder is absent:** `pagebuilder-blocks.ts` is never globbed, so
there is no block. Everything else works. The intake API is a documented
**headless** contract (`docs/api-reference.md`), so a host can build its own
form against `GET`/`POST /api/records/intake/{type}`. The admin screens,
mail, newsletter flow and landing pages need no pagebuilder at all.

**Pagebuilder's existing blocks:** `ContactForm` and `Newsletter` are not
changed in v1 and keep their preview-only success state (Q2).

---

## 9. Admin UX

The goal is no new screens beyond one public landing page.
- **Type editor** (`pages/TypeEditor.tsx`, 266 lines): a new
  `components/typeeditor/IntakeCard.tsx` shows the kind (read-only once
  set), Enabled, a checklist of public fields (sortable; ineligible types
  greyed out with the reason), the notification recipients, consent
  (required, plus text per content locale), double opt-in, and the retention
  days. It warns when `allowed_roles` is empty ("Anyone with records.view can
  read these submissions") and when `notify_to` is empty. In `FieldRow`,
  system fields show a **System** badge and are locked (no edit or delete),
  with `FieldRowSummary` reused.
- **New type:** a *From a preset* choice (Contact form, Newsletter list),
  from `utils/intake-presets.ts`, which pre-fills the existing new-type form.
- **List** (`RecordList`): unchanged machinery.
  - The preset turns on `show_in_menu`, so each form or list gets its own
    sidebar entry.
  - The default columns of an intake type include the system columns
    `sm_status` / `sm_notified_at`, plus `created_at`.
  - Filtering on `triage`, `sm_status` or `email` is the "inbox" and
    "subscribers" views.
  - The **trash** is the spam folder.
  - A banner for an empty `notify_to`, and a "not sent" badge where
    `sm_notified_at` / `sm_confirm_sent_at` is null.
  - A new `components/intake/IntakeListBanner.tsx`, beside
    `RecordListPublicUrl.tsx`, shows whether the form is enabled. It does
    not list the pages that embed it, because records cannot know them
    (Q3).
- **Editor** (`RecordEditor`, 269 lines, so the panel is its own component):
  `components/intake/IntakeDetails.tsx` shows the read-only system fields
  (IP hash and user agent collapsed). `components/intake/IntakeActions.tsx`
  shows the §4.5 buttons, with `ConfirmDialog` reused for spam and
  unsubscribe.
- **Export:** the existing CSV/JSON export, with system readonly fields
  included and `internal` ones left out. That is the subscriber export.

---

## 10. Privacy and retention

As in `design-101.md` §9, mapped onto records:
- **IP:** `sm_ip_hash = HMAC-SHA256(secret_key, f"{tenant}|{ip}")` hex. It is
  keyed, so enumerating the IPv4 space does not reverse it. Raw IPs exist
  only in the TTL'd rate-limit keys. The setting turns it off.
- **User agent:** truncated to 256 characters, and optional.
- **Consent proof:** `sm_consent_text` (a server snapshot of the type's
  text, never client text), `sm_consent_at`, `sm_consent_ip_hash` and
  `sm_confirmed_at`.
- **Unsubscribed records** keep `sm_email`, `sm_status` and
  `sm_unsubscribed_at` as a suppression record, so a re-import cannot
  resubscribe someone silently. The consent fields and any ordinary fields
  are nulled (a system write, `events.muted`). Deleting the record is an
  explicit admin action: trash, then purge.
- **Retention** (`sm_records/intake/retention.py`) is an in-process hourly
  loop started from `on_startup` and stopped on shutdown. Each tick:
  1. takes `lease("records:intake:purge", ttl=300, blocking=False)`;
  2. enumerates the tenants that have intake types with one
     `all_tenants(select(distinct RecordType.tenant_id).where(RecordType.intake.is_not(None)))`;
  3. per tenant opens a **fresh session** under `tenant_scope` (the rule in
     `tenancy.py`) and calls `hard_delete_record` for:
     - form records with `created_at < now − retention_days`, the trash
       included;
     - subscription records with `sm_status=pending` and
       `created_at < now − pending_purge_days`.
  It works in batches of `reindex_batch_size` and finishes through
  `events.commit`, so `RecordPurged` fires. The deletes are idempotent, so
  overlapping ticks are harmless.
- **Revisions** hold copies of PII. A hard delete cascades them
  (`ondelete=CASCADE`), so retention and purge remove history too. The
  README says so.
- **Erasure (GDPR art. 17):** per type, filter `email:eq:<addr>` (or
  `sm_email`), select all, then bulk purge, and repeat for each intake type.
  `docs/user-guide.md` gets the procedure. A one-shot cross-type erasure
  endpoint is out of scope.
- **Events and logs** carry identifiers only. Notification mail is the one
  place field values leave the database, by design.
- **`allowed_roles`** is the PII gate. Records' `records.view` is
  deliberately broad, so the type editor warns (Q1).

---

## 11. Tenancy

- **Single-tenant host:** everything binds `default`, as every records
  surface does today.
- **Multi-tenant host:**
  - The definition and submit routes bind the resolved tenant (the
    organisation's subdomain). An anonymous request with no tenant gets the
    shared 404.
  - The admin actions use `bind_admin` (403 `tenant_required`).
  - Mail links are built on `public_base_url` and carry the tenant in the
    MAC'd token (§4.4), so they work on the apex host. Building them on the
    tenant subdomain is Q8 of `design-101.md`, carried over as Q9 here.
  - Mail handlers and the retention loop bind each event's or row's tenant
    explicitly.
- **Census and matrix:** every new statement over an owned table names
  `tenant_id`. The census (`tests/census.py`) enforces this on Postgres.
  Every new route gets a `@covers` case in a new
  `tests/test_tenancy_isolation_intake.py`, imported by
  `test_tenancy_isolation.py`, so `test_every_route_has_an_isolation_case`
  stays green.

---

## 12. i18n

- `sm_records/locales/en.json` and `de.json` gain `records.intake.*`:
  `palette_group`, `block.*` (field labels for the Puck sidebar),
  `form.{sending, success_title, success_body, unavailable, changed, consent_required, editor_note}`,
  `errors.{form_expired, form_changed, rate_limited, captcha_failed, bad_origin, link_expired, generic}`,
  `action.{confirm_*, unsubscribe_*}`, `admin.{card_*, preset_*, system_badge, not_sent, resend, spam, not_spam, unsubscribe, roles_warning, no_recipient}`,
  and `mail.{notify.*, confirm.*}`. `scripts/check_locales.py` enforces
  parity, so every key is added in both files at once.
- Calls are `t(keys.records.intake.…)` through the existing
  `utils/i18n.ts` (the news reference implementation), with no
  `defaultValue`. Runtime families (`sm_status` badges, error codes) are
  `Record<Union, string>` of `keys.…` leaves.
- Block labels are keys resolved at render, through pagebuilder's
  `localizeConfig` (`RecordsList` does the same).
- **Content language vs UI language:**
  - The visitor sees the type's field labels, unless the page's block
    overrides them.
  - The consent text and the confirmation mail follow the page's locale
    (`sm_locale`).
  - The notification mail uses the default locale, because it goes to
    staff.
- Server error codes are stable snake_case. `endpoints/api/_error_table.py`
  and `docs/api-reference.md` list them, which `test_docs_error_table.py`
  enforces. `scripts/tests/parity_families.py` gains the intake codes if
  `scripts/http-error-parity.test.ts` covers records.
- `tests/e2e/console-de.spec.ts` walks the type editor's intake card in
  German.

---

## 13. Tests

**Unit (`modules/records/tests/`)**
- `test_intake_tokens.py`:
  - form token: sign and verify; too young; too old; tampered; wrong tenant,
    type or `schema_version`;
  - confirm token: expiry, nonce rotation, wrong tenant;
  - unsubscribe token: stable across calls, dead after rotation.
- `test_intake_spec.py`:
  - system fields injected on create and on the first kind set;
  - a client-sent `system` entry stripped;
  - a rollback re-injects the system fields;
  - an `sm_` user key refused on save but loaded when already stored;
  - the indexed ceiling counted.
- `test_intake_config.py`, the §3.3 rules:
  - unknown or ineligible public field;
  - a required non-public field with no default while enabled;
  - `is_public` together with intake gives 409;
  - `kind` change gives 409;
  - a field removal prunes `public_fields`.
- `test_intake_carry_system.py`:
  - an admin update that echoes or alters system values keeps the stored
    ones;
  - an admin create or import drops them;
  - a bulk action leaves them alone.
- `test_intake_settings.py`:
  - rate strings validated;
  - no env source (copy the existing records env-source guard).

**Integration (`app_harness` + `X-Test-Roles`, SQLite and the Postgres run)**
- `test_intake_submit.py`:
  - **happy path:** 202, record stored as draft with its system fields, a
    revision, `RecordCreated` and `FormSubmitted` after commit, and one
    `captured_mail` to `notify_to` with `sm_notified_at` set;
  - **refusals:** honeypot gives 202 with nothing stored; bad origin 403;
    wrong content type 415; body over 16 KiB 413; expired token 400;
    `schema_version` drift 409 with the definition; unknown field 422;
    per-field 422;
  - **limits:** the 6th request per IP gives 429 with `Retry-After`; the
    per-type throttle;
  - **links heuristic:** stored, trashed, `sm_spam=links`, no mail;
  - **mail edge cases:** empty `notify_to` stores and sends nothing; no
    `public_base_url` stores, sends nothing and logs a warning; a type that
    is disabled or not intake gives the shared 404.
- `test_intake_subscribe.py`:
  - **signup:** pending plus one mail; the token from the mail confirms by
    POST; GET does not confirm; expiry gives 410; a replay gives
    `already_confirmed`;
  - **unsubscribe:** by link, then a second time, then a forged link, all
    with identical 200s;
  - **re-signup:** an unsubscribed address goes back to pending with a
    rotated nonce and the old link is dead; a trashed one is restored; a
    confirmed one gets no mail and the same 202;
  - **throttles and races:** the per-email throttle; a concurrent double
    signup gives one record and two 202s.
- `test_intake_mail_durable.py`:
  - a fake `durable_transport`: the event is serialized with no token and
    no field values;
  - the handler binds the tenant and raises when there is no transport;
  - the after-commit task survives a send failure (the mark stays null and
    *Resend* recovers it).
- `test_intake_admin.py`:
  - resend, spam, not-spam and unsubscribe;
  - 409 for the wrong kind;
  - `records.view` alone gives 403;
  - `allowed_roles` narrowing gives 403;
  - CSRF missing gives 403 (`csrf_support.py`).
- `test_intake_public_routes.py`:
  - the exemption is exactly `/api/records/intake/` (`GET`/`POST`) and
    `/records/intake/` (`GET`);
  - the read API's exemption is still `GET`/`HEAD`;
  - `/admin/records/` and the admin API are not exempt;
  - a `public_route_prefix` under the intake prefix is refused.
- `test_tenancy_isolation_intake.py`, the matrix cases:
  - acme's type key on globex's host gives 404;
  - a confirm link for acme on globex's host gives the generic refusal;
  - on the apex host it binds acme;
  - the admin actions are isolated;
  - plus the census.
- `test_intake_retention.py`:
  - a per-tenant purge in fresh sessions;
  - the trash included;
  - pending subscriptions only;
  - the lease stops a second instance;
  - `RecordPurged` fired.
- `test_intake_export.py`: system readonly columns are exported, `sm_nonce`
  is not, and formula escaping still applies.

**Frontend (vitest)**
- `hooks/useIntakeForm.test.ts`: the state machine, the `form_expired`
  retry, `form_changed` keeping values, the 422 mapping, and the honeypot
  passthrough.
- `components/intake/RecordFormRender.test.tsx`: one input per type, the
  consent text from the server, the disabled editor state, the unavailable
  state, and translated errors.
- `components/typeeditor/IntakeCard.test.tsx`, `FieldRow` system lock, and
  `rules.test.ts` for the `sm_` reservation.

**E2E (Playwright; `tests/e2e/records-intake.spec.ts`, beside `records-widget.spec.ts`)**
- **Contact form:** create the *Contact form* preset, add `notify_to`, and
  enable it. Publish a page with a `RecordForm` block. Submit in an
  anonymous context and check the success state. The record appears in the
  type's list, with system fields read-only in the editor. Assert the mail
  through the test server's mail capture (the console backend log, unless
  `start-test-server.sh` exposes a capture endpoint). *Mark as spam* sends
  it to the trash, and *Not spam* brings it back.
- **Newsletter:** a *Newsletter list* `RecordForm` in the site footer.
  Subscribe, read the link from the captured mail, open it, click Confirm,
  and check that `sm_status=confirmed` filters to one row. Open the
  unsubscribe link and click it to reach unsubscribed.
- `records-intake-tenant.spec.ts` (opt-in `E2E_MULTI_TENANT=1`, in the
  multi-tenant CI job): a submission on `<org>.localhost` lands only in that
  organisation's type.
- `console-de.spec.ts`: the intake card in German.

---

## 14. Docs

- **`modules/records/README.md`:** a new "## Public forms and newsletters"
  section (the intake config, presets, system fields, the newsletter flow,
  *Spam is the trash*, retention, `allowed_roles` advice). Also rows in
  "## Settings" and an intake note in "## Multi-tenancy".
- **`docs/api-reference.md`:** the headless intake contract (§4.1 and
  §4.2), the error codes and the token formats (§4.4) for third-party
  senders.
- **`docs/architecture.md`:**
  - an "Intake" section: the type as trust anchor, injected system fields,
    the `system=` carry, and why spam is the trash;
  - the fourth committer, `intake/mail_runner.py`;
  - the new events in the events table;
  - the `intake/` package in the file layout.
- **`docs/user-guide.md`:** building a contact form and a newsletter step by
  step; triage; erasure by filter plus bulk purge.
- **`docs/operations.md`:**
  - `SM_TRUSTED_PROXY`;
  - Redis for shared rate limits;
  - `public_base_url`, which is needed for any mail;
  - the mail module;
  - `background_tasks` for durable mail;
  - the CAPTCHA CSP edit;
  - the kill switch;
  - the retention loop and its lease.
- **The design itself** is copied to
  `docs/plans/2026-10-24-records-intake-design.md`, the home of records'
  other design docs.
- **CLAUDE.md** gets one rule paragraph: "Records' intake endpoints are
  anonymous writes. The record type is the trust anchor: never trust block
  props (recipients, consent text and allowed fields live on the type). The
  `sm_` system fields are written only through the internal `system=`
  argument. The intake routes do not use `RequiresCsrf` on purpose."
- **Release notes:**
  - records' framework floor moves to `>=0.0.38,<0.1`, for
    `simple_module_core.mail`, `rate_limit_store` and leases (a range, never
    `==`; `scripts/bump_version.py` leaves dependency specifiers alone);
  - one host migration;
  - "nothing changes until a type opts in".

---

## 15. Decisions and trade-offs

| # | Decision | Trade-off accepted |
|---|---|---|
| D1 | Extend records with an intake capability (one JSON column on the type). No new package | Records grows by about 1.3k lines of Python. Every records host carries the code, which is inert until a type opts in, with a kill switch |
| D2 | The record **type** is the trust anchor (fields, consent, recipients), not the published block | Records cannot prove which block a submission came from. Source is a hint, and the throttle is per type |
| D3 | The newsletter is a generic `subscription` kind with a preset, not a seeded system type | An admin can build an odd list. The parts the flow depends on are injected and locked |
| D4 | System fields live in the payload with `system` flags and the `sm_` namespace, injected by `normalise` and carried on admin writes | Reserves a key prefix, enforced on save only. Every system write is a revision |
| D5 | Spam is the trash | Emptying the trash deletes spam, which is intended. Spam and admin-deleted records share one view, told apart by `sm_spam` |
| D6 | Stateless HMAC confirm and unsubscribe tokens carrying the tenant, minted at send time | Rotating `secret_key` kills every outstanding link. The two link routes bind the link's tenant |
| D7 | Fixed intake prefixes, separate from the configurable read prefix | An operator cannot move the intake API. That keeps the read API `GET`-only and the exemption math trivial |
| D8 | No session CSRF on public submit. JSON, Origin and a signed token instead | Relies on CORS preflight semantics. A same-site attacker can only send spam, which the rate limits bound |
| D9 | Mail via the outbox when present, otherwise an after-commit task with a fourth documented committer | The no-outbox path can lose mail on a crash. That is visible ("not sent") and recoverable (*Resend*) |
| D10 | A live definition fetch and a `schema_version` in the token | One extra GET per page view with a form, plus a 409 path for visitors who loaded the form before an edit |
| D11 | Allowlisted `public_fields`, with save-time consistency rules | The admin must tick a new field to publish it. A required non-public field blocks the save while the form is enabled |
| D12 | Honeypot hits get a fake 202 and nothing is stored | False positives are invisible, as in `design-101.md` D4 |
| D13 | No new permissions. `allowed_roles` gates the PII | Out of the box, a `records.view` holder can read submissions. The type editor warns |

---

## 16. Open questions (each with a recommended default)

| | Question | Recommended default |
|---|---|---|
| Q1 | Should enabling intake *require* non-empty `allowed_roles`? | **No: warn in the type editor.** Requiring it would block single-admin installs |
| Q2 | Pagebuilder's existing `ContactForm`/`Newsletter` blocks: leave them, add an editor note ("preview only, use Form (Records)"), or hide them from the palette when `RecordForm` is registered? | **Leave them in v1** and document `RecordForm` as the working one. Follow up with a deprecation note in pagebuilder |
| Q3 | Show the admin which pages embed a form? It needs pagebuilder to report block usage | **No in v1** |
| Q4 | Over the per-type cap: 429, or store and mark throttled? | **429** |
| Q5 | File an upstream framework issue for `MailMessage.reply_to` and headers (`List-Unsubscribe`, `List-Unsubscribe-Post`)? | **Yes.** v1 ships without them. The unsubscribe endpoint already accepts the RFC 8058 form-encoded POST |
| Q6 | Encrypt `intake_captcha_secret` at rest? | **No.** Mask it, like the SMTP password |
| Q7 | Import subscribers (Mailchimp migration) with their status and consent proof? Today import drops system values | **Not in v1.** Later: an `--intake-trusted` CLI-only import flag |
| Q8 | Should a form type's records be marked read when an admin opens them (the `new → read` state of `design-101.md`)? | **No.** The preset's ordinary `triage` field is the workflow, and the admin can edit it |
| Q9 | In multi mode, build mail links on the tenant's subdomain? | **`public_base_url` in v1.** The token names the tenant. Revisit when tenants exposes a "tenant public URL" helper |
| Q10 | Default `retention_days`? | **365** (and 30 for pending subscriptions) |
| Q11 | Welcome mail after confirmation? | **Off** (not built) |

---

## 17. Size and PR split

**Size: M+**, about 1,300 lines of Python, 800 of TS/TSX and 1,200 of tests,
in 4 PRs merged in order. The forms design was **L**: about 2,000 Python,
1,200 TS and 1,500 tests in 5 PRs, plus a new package with its own
release, docs skeleton and PyPI publisher. This one is about **35–40%
smaller in code**, with **no new package, table, permission or admin page**,
and no pagebuilder change at all.

Each PR is green and shippable on its own. Until PR 2, no route accepts
anonymous writes. Until PR 4, nothing renders on a public page.

1. **records: intake config and system fields (M).**
   - The `records_type.intake` column, the host migration, `IntakeConfig`,
     `intake/spec.py`, `intake/config.py` (§3.3), `FieldDefinition.system`,
     and the `sm_` key reservation (Python and `rules.ts`).
   - `normalise` injection, `_payload.carry_system`, the `system=` argument
     on `create_record`/`update_record`, export skipping internal fields,
     and `TypeRead`/`TypeUpdate.intake`.
   - Type editor: `IntakeCard` (with enabled shown but no public routes
     yet), the `FieldRow` system lock, the presets, and `IntakeDetails`.
   - `settings_intake.py` and en/de keys for the above.
   - Extract `RecordsModule.on_startup`'s body into `boot.startup()` so
     later PRs have room under the cap (`module.py` is at 289 lines).
   - Framework floor `>=0.0.38`.
   - Tests: spec, config, carry, settings.
   - No behaviour change for existing types.
2. **records: public submissions and mail (M).**
   - The intake public router and exemption, `IntakeErrorRoute`, the guards
     and abuse layers §5.0–5.5 and §5.7, the body-limit tier, form tokens,
     the definition and submit routes for the form kind, and the
     `FormSubmitted` event.
   - `intake/mail.py` and `mail_runner.py` (outbox and after-commit),
     `register_event_handlers`, the notification template, and the admin
     `resend`/`spam`/`not-spam` routes with `IntakeActions`.
   - The isolation matrix cases, the public-route asserts, and the
     error-table and api-reference entries.
   - Tests: submit, admin, durable, routes, isolation.
3. **records: newsletter double opt-in (M).**
   - The subscription kind's signup state machine, confirm and unsubscribe
     tokens, the link-tenant binding, and the `IntakeAction` public page
     with its view router and exemption.
   - The confirmation template, the per-email throttle, `SubscriptionChanged`,
     the admin unsubscribe route, and the consent-nulling.
   - Tests: subscribe and isolation additions.
4. **records: RecordForm block, retention, CAPTCHA and docs (M).**
   - `RecordForm` (block, render, inputs, `useIntakeForm`,
     `intake-api.ts`), registered with `layout: true`.
   - The retention loop with its lease, and CAPTCHA (Turnstile and hCaptcha
     verify, client loader and CSP warning).
   - README, architecture, api-reference, user-guide and operations docs,
     the `docs/plans/` copy, the CLAUDE.md rule, and the release notes.
   - Vitest, e2e `records-intake.spec.ts`, the multi-tenant spec, and the
     German console walk.

   If PR 4 runs long, CAPTCHA splits off as PR 5 (S). It is independent of
   everything else.
