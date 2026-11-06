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
| 4 | (later) | sending: freeze, single dispatcher + budget ledger, daily cap and per-minute throttle, retries (pre-acceptance only), pause/resume/cancel, bounce classification, **the unsubscribe page and one-click POST** |
| 5 | (later) | tracking (open, click) and reports |
| 6 | (later) | segments and the subscriber screen |
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
