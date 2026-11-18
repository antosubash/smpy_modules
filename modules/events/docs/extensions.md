# Writing a plugin for events

A second package can put its own dates on a calendar (a **source**), add an event
**type** with its own data (`extra`), and contribute UI (chips, details, editor and
settings sections, toolbar items). It does so from two files with fixed names, looked
up by events and never imported by a path:

| File | What it holds |
|---|---|
| `<package>/events_extensions.py` | `def register(registry)`: sources and types |
| `<package>/events-extensions.ts` | lazy UI registrations |

A package is a plugin when it is a module (it has the `simple_module` entry point) and
ships the file. Records ships both, as `records:dates` (see the end).

Everything a plugin imports from events is in one place: `sm_events.contracts.extensions`
on the Python side and `@simple-module-py/events` on the TypeScript side. Nothing else
is public, and `scripts/check_sibling_contracts.py` and `scripts/check_ts_imports.py`
refuse anything else.

## Registration, and why a file and not `on_startup`

Events loads plugins once, in the web process (its `on_startup`) and on the first
registry read in a worker, then **freezes** the registry: a later `add_source` or
`add_type` raises `RegistryFrozenError`. A Celery worker runs no module hook, so a
registration in `on_startup` would be missing there; the file is read by both, through
one code path. A plugin that raises while loading fails the load (and the boot), with
the plugin named; the registry is emptied so a retry starts clean.

Install a plugin **identically in the web image and in every worker image**. A worker
without it treats its ids as "not installed" (see below) and never errors.

Ids are `<entry-point name>:<name>` (`^[a-z][a-z0-9_]*:[a-z][a-z0-9_-]{0,47}$`), and the
part before the colon must be your entry-point name. The built-in `events` source and
`event` type carry no colon and cannot be registered. A duplicate id, a malformed
object, a wrong signature, a schema that cannot be turned into JSON and a **secret-typed
settings field** are refused at registration.

## A source

```python
# holidays/events_extensions.py
from datetime import date
from pydantic import BaseModel, ConfigDict
from sm_events.contracts.extensions import SourceContext, SourceOccurrence


class HolidaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = "AT"


class Holidays:
    id = "holidays:public"
    label_key = "holidays.source.label"  # resolved at render; the id shows when there is none
    public = True  # see "What a public source must guarantee"
    color = None
    icon = "calendar"
    settings_model = HolidaySettings

    async def occurrences(self, ctx: SourceContext, start, end):
        return [
            SourceOccurrence(
                key="new-year",
                title="New Year's Day",
                all_day=True,
                start_date=date(start.year, 1, 1),
                end_date=date(start.year, 1, 2),
            )
        ]


def register(registry) -> None:
    registry.add_source(Holidays())
```

An admin enables the source per calendar (Calendars, **Sources**), with its settings.
`occurrences(ctx, start, end)` returns `SourceOccurrence`s (never an ORM object): timed
(`start` and `end`, aware) or all-day (`all_day=True`, `start_date`, `end_date`
exclusive), a `key` unique within the answer, a plain-text `title`, and optionally `url`,
`color`, `status`, `lang`, `timezone`, `updated_at`. It has no `source`, `calendar_id`,
`editable` or `type`: events fills those in, so a source cannot claim another's id or
calendar. An optional `async check_settings(sctx, settings)` raises
`SourceSettingsError(loc, message)` for a settings value the model cannot judge; it runs
when an admin saves. `SourceError("some_code")` from `occurrences` becomes that code in the
source's status instead of the generic `raised`.

### What the runner does around your call

* **Its own connection.** `ctx.db` is a session of its own (its own connection, bound to
  the request's tenant), rolled back and closed afterwards, never the request's session. A
  timeout, a cancelled statement, bad SQL or a client that disconnects can only break
  that connection. On Postgres the database stops the statement at the call's budget
  (`SET LOCAL statement_timeout`). It is **read-only**: `commit`, `rollback` and `close`
  raise, and a write is refused (`wrote`) and discarded.
* **Budget.** 2 s per call, 5 s for all calls of one read (a call needs 0.25 s left to
  start), at most 16 calls per read, run one after another. At most 500 items per answer
  (the earliest by time are kept and the status is `truncated`); an answer over 5,000 is
  refused unread.
* **Limits you must know.** A plugin that blocks the event loop with synchronous CPU work,
  or swallows `CancelledError`, cannot be pre-empted: it delays the answer past its
  timeout. On SQLite a running query finishes before its connection can be closed.
  Only an engine that shares one connection between sessions (the in-memory test engine)
  runs your call on a savepoint of the request's session instead; a file or Postgres engine never does.
* **Validation.** Any one invalid item rejects the whole answer (`invalid_item`,
  `duplicate_key`): aware `start < end`, an all-day `start_date < end_date`, at most 366
  days (`ITEM_MAX_DAYS`; clip a longer one yourself), a known timezone, the title (at most
  `ITEM_TITLE_MAX` characters) stripped of control and direction characters (kept as
  text; every renderer escapes it), a `url` that is a same-origin path or an `http(s)` URL
  without credentials, a `#rrggbb` colour. Every item is validated again, so
  `model_construct` buys nothing. An item outside the window is dropped, not an error.
* **Status.** Each `(calendar, source)` reports `ok`, `truncated`, `failed`, `timeout`,
  `skipped` or `not_installed` to the console, which says so in words. A failing source
  never fails the read; the calendar's own events still show. Exceptions are logged with the
  source id and the exception class only.

### Who sees what

Events decides which calendars a viewer may see, and the source decides what it returns
for that viewer: `ctx.viewer` (`user_id`, `roles`, `permissions`, `role_map`) is `None` on
every public surface. A signed-in read without a viewer skips every source (`no_viewer`).
Plugin items appear in the console, the public grid (`/api/occurrences`) and the feeds
only; never in the server-rendered upcoming list, the sitemap or JSON-LD. A category
filter, or a type filter without the default type, excludes plugin items.

**What a public source must guarantee.** `public = True` sources are the only ones called
for an anonymous read, and only on public calendars, with `viewer=None`. A public source
must return only data that is public in its own module. The default is `public = False`.
A failed public source makes the public answer `no-store` (a failure is not cached).

**Settings are not secret.** They are stored in the clear and shown to whoever manages the
calendar. Keep a secret in your own module's (sealed) settings and name it from here.

## An event type

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict
from sm_events.contracts.extensions import EventType


class TalkExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")  # required
    speaker: str
    room: str | None = None
    level: Literal["intro", "advanced"] = "intro"


TALK = EventType(
    id="acme:talk",
    label_key="acme.types.talk",
    extra_model=TalkExtra,
    public_fields=frozenset({"speaker"}),  # the only fields a public page may carry
)


def register(registry) -> None:
    registry.add_type(TALK)
```

`extra` is validated against the model on every write (at most 16 KiB, unknown keys
refused) and stored as the model's JSON dump. The type is **immutable** after creation. An
event whose type is not installed keeps its `type` and `extra` byte for byte through every
path (edits, overrides, workflow, trash, restore, the scheduled publish in a worker, the
revision snapshot); it renders as a plain event, shows a notice in the editor and refuses a
change to `extra` (`type_not_installed`). Public pages receive `public_extra` (your
`public_fields`) and never `extra`; it is absent from the API, ICS and JSON-LD.

## Frontend

```ts
// acme/events-extensions.ts
import { registerEventType, registerSource, registerToolbarItem } from '@simple-module-py/events';

registerEventType({
  id: 'acme:talk',
  EditorSection: () => import('./ui/TalkSection'),   // a default export
  PublicDetail: () => import('./ui/TalkPublic'),
});
```

Only that import is static (types may be `import type`); every component is a lazy
loader (a repo test checks this). Events loads the files through a lazy glob, one at a time:
a file that fails to load, or throws while registering, is logged once by path and skipped;
the console shows a small notice, public pages nothing. Each component runs inside an error
boundary, so one that throws shows the default (or nothing). Slots: `Chip`, `Detail`
(console), `PublicDetail` (public), `EditorSection` (`extra`, `onChange`, `errors` by path
under `extra`, `readOnly`), `SettingsSection` (a source's settings), toolbar items. Props are
readonly and carry no session, CSRF token or API helper. A plugin on the public site must not
call console APIs (an anonymous visitor gets a 401) and must not inject scripts (the page runs
under the nonce CSP). Labels are keys resolved at render.

## Bus events

`sm_events.contracts.events` has nine events (published, rescheduled, cancelled, deleted,
unpublished, reinstated, occurrence skipped, restored, updated). Each is published in process
after the commit and, when the host has the `background_tasks` outbox and the event has
durable handlers, **also written to the outbox in the writer's own transaction** and delivered
**at least once** by a worker (the framework's retries, backoff and dead-letter state). There
is **no ordering** between two events of one `event_id`: re-read the event instead of trusting
the order. In-process subscribers see web-process changes only; the scheduled publish reaches
durable subscribers. Subscribe with `bus.subscribe_durable(Type, handler, name="<stable>")` in
`register_event_handlers`, before any `if app is None: return`. Payloads are identifiers,
instants and field names: never a title, personal data or `extra`.

**An import is silent.** Events created or changed by an `.ics` import (new events, updates and
override changes alike) publish nothing: no in-process event and no outbox row, so 5,000
imported events are not 5,000 notifications. A plugin that must know about imported events
re-reads the calendar instead of waiting for a bus event.

## Versioning and testing

Depend on events with a `>=` range, as an optional extra, with a `# floor:` comment naming
the release that first shipped what you use (`sm_events.contracts.extensions` first ships in
0.0.16); never `==`. `scripts/check_sibling_contracts.py` checks every contract name you import
against the floor. Keep every import of `sm_events` inside your extension file (lazily, as
records does) so your package installs and runs without events. In tests, put your source in a
fresh registry through events' loader and call it with a hand-built `SourceContext`.

## Worked example: records

Records' optional `events` extra registers `records:dates` from `sm_records/events_extensions.py`
(which imports `sm_records.integrations.events` only inside `register`) and
`sm_records/events-extensions.ts`. It reads through `sm_records.contracts.dated`, which pins the
tenant and applies records' own access rules: published, untrashed records of a type the viewer
may read (`records.view` and the type's `allowed_roles`, widened by a `records.type.<key>` grant,
never by the admin wildcard); for the public, only an `is_public` type. A type the viewer may not
read is indistinguishable from one that does not exist.
