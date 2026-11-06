# Newsletter module — roadmap

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`

The spec's "Delivery order" splits into PRs that each ship working, tested
software. Each PR gets its own plan, written when the previous PR is merged,
so it is planned against the code as it then stands. Each one goes through
`/ship` (memory: ship then merge one by one).

| PR | Plan | Delivers |
|---|---|---|
| 1 | `2026-11-03-newsletter-pr1-contracts.md` | records `contracts.newsletter` (iter incl. status, count, by-uuid, unsubscribe, tags, can_read_list); news `contracts.articles` (search, card) |
| 2 | `2026-11-03-newsletter-pr2-scaffold.md` | `modules/newsletter` scaffold per `docs/adding-a-module.md` and `docs/module-layout.md`; models, migrations, settings, tenancy, permissions; suppression mirror from `SubscriptionChanged` and the hourly suppression reconcile; the SMTP password endpoint (`PUT /api/newsletter/settings/smtp-password`); records contract additions (`subscription_lists`, `subscription_list_tenants`, `iter_subscribers(include_trashed=)`) |
| 3 | `2026-11-03-newsletter-pr3-campaigns.md` | campaigns + content: block model, email renderer (HTML + text), Puck editor, preview, article/page cards, test send over SMTP transport, settings page |
| 4 | `2026-11-03-newsletter-pr4-sending.md` | sending: freeze, single dispatcher + budget ledger, daily cap and per-minute throttle, retries (pre-acceptance only), pause/resume/cancel, bounce classification, **the unsubscribe page and one-click POST** |
| 5 | `2026-11-03-newsletter-pr5-tracking.md` | tracking (open, click) and reports |
| 6 | `2026-11-03-newsletter-pr6-segments.md` | segments, campaign audiences (`all`, `tag:`, `segment:`), the subscriber screen with tags and admin unsubscribe, suppression lifts (spec amendment 11) |
| 7 | (later) | Mailchimp import, with records' `import_subscribers` and a tag-choices contract added there, where its only caller is; docs; e2e spec |

## Notes for PR 4 (from PR 3)

- The unsubscribe page must answer `/newsletter/u/test` like a forged token: the
  same page, and a POST that changes nothing (previews and test sends link there).
- The dispatcher reuses `sending.lock.dispatch_lock` and `sending.budget.admit`,
  renews the SQLite lease before each SMTP call, re-reads the campaign's status
  inside the lock, and stamps each row per attempt.
- Map the transport's `failed` outcome (known pre-acceptance failure, not counted
  against the budget) to the retry path.
- The worker app needs `app.state.sm_newsletter.tenancy` and `app.state.tenants`
  so `render_context` can compute each tenant's public origin.

## Notes for PR 5

- Reuse `core.tokens.sign` for `/o/` and `/c/`: one token per send, the same MAC
  scheme as `/u/`.
- Link rewriting must happen in `campaigns/snapshot.py`, writing `newsletter_link`
  rows when the campaign is scheduled (the worker only personalises the snapshot).
- The tag audience moved to PR 6 (S3): `tag:` and `segment:` stay
  `422 audience_unsupported` until then.

## Notes for PR 6 (from PR 5)

- The report's timeline is a window: hourly for the first 72 hours from the
  campaign's `started_at` (UTC), then daily for at most 90 days, exclusive end
  (`tracking/timeline.py`). Events outside it count in the totals only.
- Segments need no tracking change: tracking is per send and link, and never
  reads the audience.

## Notes for PR 7 (from PR 6)

- The tag-choices **read** shipped in PR 6 (`list_fields`, in
  `sm_records.contracts.newsletter_admin`); PR 7 adds only `add_tag_choices`, the
  write, beside `import_subscribers`.
- The import must never emit `pending → confirmed` (PR 2): that is the one event
  that clears suppressions.
- Imported people's "signed up" (records' `created_at`, what a segment's "Signed up"
  rule reads) is the import time.
- The e2e "send to a tag" uses the audience picker's *A tag*.
