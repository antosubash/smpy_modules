# simple_module_newsletter

Newsletters for SimpleModule hosts. A campaign is written once, rendered to
HTML and plain text, and sent over SMTP (the Google Workspace relay) to the
confirmed subscribers of a list, throttled to a daily cap and a per-minute rate.

**Subscribers do not live here.** Lists, subscribers, their double opt-in state
and tags are `simple_module_records` data; newsletter reads them only through
`sm_records.contracts.newsletter`. What newsletter owns is the campaign, its
sends and clicks, and the per-tenant suppression list (addresses that must never
be mailed again: unsubscribes, hard bounces, complaints). Design:
`docs/superpowers/specs/2026-11-03-newsletter-module-design.md` in the source
repo; the guide is [`docs/index.md`](docs/index.md).

**Status: sending.** You can write a campaign in a Puck editor, preview it as the
server renders it, send a test to up to five addresses, and send it to a list:
a beat task (`newsletter.dispatch`) freezes the audience and sends within a
daily cap and a per-minute rate, with retries, pause, resume and cancel, and an
unsubscribe page with RFC 8058 one-click. Open and click tracking and a
campaign report are described in [`docs/tracking.md`](docs/tracking.md). See
[`docs/content.md`](docs/content.md) for blocks, merge fields and the URL rules,
[`docs/sending.md`](docs/sending.md) for how sending works and
[`docs/operations.md`](docs/operations.md) for what must run (worker and beat,
the secret, the DKIM checklist). Segments, campaign audiences, the subscriber
screen and suppression lifts: [`docs/audience.md`](docs/audience.md).

## Install

```bash
pip install simple_module_newsletter
```

Add `simple_module_newsletter` to your host's dependencies; for an in-repo
checkout, resolve it from the workspace:

```toml
[tool.uv.sources.simple_module_newsletter]
workspace = true
```

The module needs the framework's `settings` and `background_tasks` modules and
`simple_module_records`. The `news` and `pagebuilder` extras add article and page
cards to the editor; without them those blocks are hidden. Migrations live in the consuming host (`make
migration`), never in the wheel.

## Usage

### Settings

Settings are DB-backed (the framework's settings module), never environment
variables. Configure them on the Settings screen or with
`scripts/set_setting.py`. The SMTP password is the exception: it is stored
encrypted under the host's secret key and written only through
`PUT /api/newsletter/settings/smtp-password` (needs `newsletter.manage`
and `settings.edit`; `scripts/set_setting.py` would
store it in plaintext, which workers refuse: the dispatcher does not run until it is
re-saved through the endpoint, so always use the endpoint). The generic Settings screen
refuses newsletter writes: use the module's own page, `/admin/newsletter/settings`.
Changing the SMTP host, port, security or username clears the stored password.

### Screens

| Screen | URL | Needs |
| --- | --- | --- |
| Campaigns | `/admin/newsletter/` | `newsletter.view` |
| Segments | `/admin/newsletter/segments` | `newsletter.view` (edit: `newsletter.edit`) |
| Subscribers | `/admin/newsletter/subscribers` | `newsletter.view` and `records.view` |
| Suppressions | `/admin/newsletter/suppressions` | `newsletter.manage` |
| Settings | `/admin/newsletter/settings` | `newsletter.manage` |

### Permissions

| Permission | Allows |
| --- | --- |
| `newsletter.view` | See campaigns and preview them, reports, segments; with `records.view`, the subscriber screen |
| `newsletter.edit` | Create and edit campaigns and segments; tag and untag subscribers (with `records.view`) |
| `newsletter.send` | Send a test; later, start, pause, resume and cancel a send |
| `newsletter.manage` | The settings page (saving it and the SMTP password also need `settings.edit`), the suppressions screen and its lifts, and unsubscribing a subscriber (with `records.view`) |

Every entry point binds a tenant: a single-tenant host uses `default`, a
multi-tenant host the organisation the framework resolved (403
`tenant_required` for admin routes, 404 for public ones when none).
