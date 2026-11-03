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
| 2 | this package: scaffold, tenancy, settings, models, suppressions | in progress |
| 3 | campaigns, content blocks, renderer, test send | planned |
| 4 | sending, throttling, retries, unsubscribe page, hourly reconcile | planned |
| 5 | open and click tracking, reports | planned |
| 6 | segments and the subscriber screen | planned |
| 7 | Mailchimp import, docs, e2e | planned |

## Settings

DB-backed through the framework's settings module; no environment variables.
`smtp_password` is stored encrypted and written only through
`PUT /api/newsletter/settings/smtp-password` (it arrives later in this PR). The
generic Settings screen refuses newsletter writes: a dedicated settings page
arrives in PR 3.

## Suppressions

A suppression says "never mail this address". Suppressions are **tenant-wide**:

- An `unsubscribed` row suppresses the address for **every list in the tenant**.
  The row records the list it came from as provenance, and there is one row per
  list.
- `hard_bounce`, `complaint` and `imported_cleaned` rows are **address-wide**.
- The address is stored as `email_hash = sha256(email.strip().lower())`, unkeyed.
- A confirmation on list L clears L's `unsubscribed` row and any `hard_bounce` or
  `imported_cleaned` row created at or before the confirmation. It never clears
  a `complaint`, and never another list's opt-out.
- An hourly reconcile re-adds the opt-outs records holds. It only adds; it never
  removes a suppression.

Suppression wins over every other rule at send time.
