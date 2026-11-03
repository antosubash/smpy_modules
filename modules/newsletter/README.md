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

**Status: scaffold.** The package registers its permissions and locales and
nothing else yet: no screens, and one admin API endpoint, the one that sets the
SMTP password. Campaigns, sending and tracking arrive in later pull requests.

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
`simple_module_records`. Migrations live in the consuming host (`make
migration`), never in the wheel.

## Usage

### Settings

Settings are DB-backed (the framework's settings module), never environment
variables. Configure them on the Settings screen or with
`scripts/set_setting.py`. The SMTP password is the exception: it is stored
encrypted under the host's secret key and written only through
`PUT /api/newsletter/settings/smtp-password` (`scripts/set_setting.py` would
store it in plaintext, accepted with a warning; use the endpoint). The generic Settings screen
refuses newsletter writes; a dedicated settings page arrives in a later PR.

### Permissions

| Permission | Allows |
| --- | --- |
| `newsletter.view` | See campaigns, reports and suppressions |
| `newsletter.edit` | Create and edit campaigns |
| `newsletter.send` | Start, pause, resume and cancel a send |
| `newsletter.manage` | Settings and the SMTP password |

Every entry point binds a tenant: a single-tenant host uses `default`, a
multi-tenant host the organisation the framework resolved (403
`tenant_required` for admin routes, 404 for public ones when none).
