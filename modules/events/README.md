# simple_module_events

Calendars and events for SimpleModule hosts. Events are timezone-aware and can
recur; calendars are owned, carry a visibility (`private`, `internal` or
`public`) and can be shared with individual users through the framework's
`sharing` module. Later releases add public pages, ICS feeds, reminders and
registration. Design: `docs/superpowers/specs/2026-11-17-events-module-design.md`
in the source repo; the guide is [`docs/index.md`](docs/index.md).

**Status: PR 1 of 10.** The package, its permissions, DB-backed settings, the
tenancy guard, the calendar access policy, calendars and categories (API and
screens) and the tables for events exist. Events themselves arrive in PR 2.

## Install

```bash
pip install simple_module_events
```

Add `simple_module_events` to your host's dependencies; for an in-repo
checkout, resolve it from the workspace:

```toml
[tool.uv.sources.simple_module_events]
workspace = true
```

The module needs the framework's `settings` and `sharing` modules. Migrations
live in the consuming host (`make migration`), never in the wheel: the host
autogenerates its own revision against the module's `events_*` tables.

## Usage

### Permissions

| Permission | Allows |
| --- | --- |
| `events.view` | See calendars and categories the policy lets you read |
| `events.edit` | Create calendars (you become the owner) and write events on internal and public calendars |
| `events.publish` | Publish events |
| `events.manage` | Act on every calendar, manage categories, transfer ownership |

### Settings

Settings are DB-backed (the framework's settings module), never environment
variables. Configure them on the Settings screen or with
`scripts/set_setting.py`: `default_timezone` and `content_locales` (restart).
