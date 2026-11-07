# Newsletter documentation

`simple_module_newsletter` sends campaigns to the subscriber lists that
`simple_module_records` holds. Records owns the subscribers and their opt-in
state; newsletter owns the campaigns, the sends and the suppression list. The
design is `docs/superpowers/specs/2026-11-03-newsletter-module-design.md` in the
source repository, and the delivery order is
`docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`.

## Status

| PR | Delivers | State |
| --- | --- | --- |
| 1 | records `contracts.newsletter`, news `contracts.articles` | merged |
| 2 | this package: scaffold, tenancy, settings, models, suppressions, hourly reconcile | merged |
| 3 | campaigns, content blocks, renderer, preview, Puck editor, test send, settings page | merged |
| 4 | sending, throttling, retries, unsubscribe page | this PR |
| 5 | open and click tracking, reports | planned |
| 6 | segments and the subscriber screen | planned |
| 7 | Mailchimp import, docs, e2e | planned |

Sending is described in [`sending.md`](sending.md) (status machine, freeze, the
dispatcher, verdicts, the unsubscribe route) and what has to run for it in
[`operations.md`](operations.md) (worker and beat, the secret, the DKIM
checklist, the relay).

## Campaigns and content

A campaign is a draft with a subject, preheader, list, sender overrides and a
body of blocks: heading, rich text, image, button, divider, spacer, and article
and page cards. The renderer (`sm_newsletter.content.render`) turns the body into
a table-based, inline-styled HTML part and a plain-text part, with a fixed footer
(why you got this, the postal address, unsubscribe) and merge fields
(`{{first_name}}`, `{{first_name|fallback}}`, `{{unsubscribe_url}}`). Rich text is
re-serialised from an allow-list at save and at render. Details, the URL rules
and the golden files: [`content.md`](content.md).

- **Screens.** `/admin/newsletter/` (campaign list), `/admin/newsletter/campaigns/{id}`
  (a newsletter-only Puck editor with a 600 px single column, a preview pane and a
  test-send dialog) and `/admin/newsletter/settings`. The sidebar has Campaigns
  (`newsletter.view`) and Settings (`newsletter.manage`).
- **Writes are revision-guarded.** PATCH and card Refresh carry `expected_revision`;
  a stale one is `409 stale`, a campaign that left draft `409 not_a_draft`.
- **List access is re-checked on every campaign request**, so a list restricted
  after a campaign was made hides the campaign (404) from callers who can no
  longer read it.
- **Cards** are snapshotted when inserted, through `news.contracts.articles` and
  `pagebuilder.contracts.cards` only; Refresh re-reads one. `news` and `pagebuilder`
  are optional extras (`simple_module_newsletter[news]`, `[pagebuilder]`); without
  one, its card block is hidden from the palette and its routes answer
  `409 integration_unavailable`.
- **Links** in content are absolute against the campaign tenant's public origin;
  the unsubscribe link and the logo (`/newsletter/brand/logo`, the system-scope
  branding logo, anonymous) use `public_base_url`. A test send needs
  `public_base_url` set (`422 public_base_url_required`).
- **Preview** is the server's render in a sandboxed iframe. Viewers
  (`newsletter.view`) preview the saved campaign; unsaved content is previewed
  only by `newsletter.edit` holders on a draft.
- **Test send** (`newsletter.send`): up to 5 addresses, `[TEST] ` subject. It runs
  under the install-wide dispatch lock (`sending/lock.py`) and counts against the
  rolling daily and per-minute budget through `newsletter_send_attempt`.
  Admission is all-or-nothing: over budget is `429 send_budget_exhausted`, nothing
  sent and no rows written. Per-recipient outcomes are `accepted`, `rejected`,
  `unknown` and `failed` (a known pre-acceptance failure; not counted). Its unsubscribe link
  is `<public_base_url>/newsletter/u/test`, which PR 4's page treats like a forged
  token. No campaign is sent yet: sending arrives in PR 4.
- **Transports.** `smtp` (aiosmtplib; STARTTLS or implicit TLS; `List-Unsubscribe`,
  `List-Unsubscribe-Post` and `Precedence: bulk` headers) and `console`, which logs
  and keeps a per-tenant capture readable at `GET /api/newsletter/outbox`
  (`newsletter.manage`). On SQLite the dispatch lock is a lease row held for 120 s.

## Settings

DB-backed through the framework's settings module; no environment variables.
The dedicated page is `/admin/newsletter/settings` (`newsletter.manage`; saving
also needs `settings.edit`). The generic Settings screen refuses newsletter
writes (`manage_url`).

- `GET /api/newsletter/settings` needs `newsletter.manage`.
  `PUT /api/newsletter/settings` needs `newsletter.manage` **and** `settings.edit`,
  like the password endpoint.
- A PUT that changes `smtp_host`, `smtp_port`, `smtp_security` or `smtp_username`
  **clears the stored `smtp_password`** in the same write and answers
  `password_cleared: true`, so nobody can point the relay at another server and
  harvest the credential at AUTH. The page warns before saving.
- `from_name`, `from_address` and `reply_to` refuse CR, LF and control characters
  (422, no echo).
- Input is bounded: `smtp_host` 253, `smtp_username` 320, `from_name` 200,
  `physical_address` 500 characters (422 above that). A malformed body to the
  password endpoint is `422 invalid_password` and never echoes the input.
- `smtp_password` is stored encrypted and written only through
  `PUT /api/newsletter/settings/smtp-password` (needs `newsletter.manage` and
  `settings.edit`; `scripts/set_setting.py` would store it in plaintext, which
  the workers refuse: the dispatcher does not run until it is re-saved through the endpoint).

## Suppressions

A suppression says "never mail this address". Suppressions are **tenant-wide**:

- An `unsubscribed` row suppresses the address for **every list in the tenant**.
  The row records the list it came from as provenance, and there is one row per
  list.
- `hard_bounce`, `complaint` and `imported_cleaned` rows are **address-wide**.
- The address is stored as `email_hash = sha256(email.strip().lower())`, unkeyed.
- A double-opt-in confirmation on list L (the subscriber following records'
  confirm link) clears L's `unsubscribed` row and any `hard_bounce` or
  `imported_cleaned` row created at or before the confirmation. It never clears
  a `complaint`, and never another list's opt-out. Nothing else clears a
  suppression: a signup on a single-opt-in list is confirmed at once but proves
  nothing about the mailbox (anyone can type the address), so it clears nothing.
- An hourly reconcile re-adds the opt-outs records holds, trashed subscribers
  included. It only adds; it never removes a suppression. It is the Celery task
  `newsletter.reconcile_suppressions` on the `newsletter` queue (`make worker`
  serves it; beat schedules it).

Suppression wins over every other rule at send time.
