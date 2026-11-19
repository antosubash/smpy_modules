# Pagebuilder blocks and the card contract

Two ways another module shows events: **blocks** on a pagebuilder page, and **cards** for a
newsletter. Both are the *public* projection of an event, so both start from the same gate as the
public pages (`core/access/public.py`): a **published** event of a **public** calendar, never
trashed, in the bound tenant. A draft, an event in review or scheduled, an event of an internal or
private calendar, a trashed event or calendar and another organisation's event are never found,
never carded and never listed, and none of them is told apart from an id that does not exist.

## The card contract (`sm_events.contracts.cards`)

For a sibling module (newsletter today). `mounted(app)` says whether events runs on an app at all.

| Function | Answers |
| --- | --- |
| `get_event_card(session, *, tenant_id, event_id, locale=None)` | one `EventCard`, or `None` |
| `search_events(session, *, tenant_id, pattern, locale=None, limit=20, upcoming_only=True)` | a list of `EventCard` |

**The tenant is pinned by the contract**, not by the caller: it is bound with `tenant_scope` and
added as a `WHERE`, so naming a tenant while nothing is bound returns only that tenant's events,
naming another one while a tenant is bound raises `TenantIsolationError`, and an invalid id raises
`ValueError` before any SQL. A session that cannot run an unscoped statement answers "nothing".

**Which occurrence.** A one-off is carded whatever its date. A series is carded at its **next**
occurrence over the coming year (one in progress counts); a skipped one never appears, a moved one
is at its new time and a cancelled one is marked. A series with nothing left has no card. The text
is the one in the asked language, else the default language's, else the first, and the paths carry
that language's prefix.

**The fields of a card**, and nothing else: `id`, `title`, `summary` (plain text, `""` when none),
`starts_at` and `ends_at` (aware UTC), `all_day`, `start_date` and `end_date` (all-day only, the end
exclusive), `timezone`, `attendance_mode`, `venue_name`,
`address`, `image_url` (an absolute http(s) address, else `""`), `path` and `ics_path`
(site-relative), `locale` and `cancelled`. The caller formats the dates in its own language and
makes the paths absolute from its own public origin.

**`id` is the event's internal id.** It exists so a consumer can look the card up again. It must
never be rendered into public HTML, an email, a feed or page JSON: the public surface is keyed by
slug and carries no event ids.

**Search.** `pattern` is a `LIKE` pattern with `\` as the escape character; the caller escapes it.
It matches a title in any language. Upcoming events come first by start; with
`upcoming_only=False` past one-offs follow, newest first. At most `limit` cards (1 to 50), chosen
from at most 50 matching events of each kind, so a long list is narrowed by typing more. The read
is a fixed number of statements however many events match.

## The anonymous routes

The blocks read three routes at a **fixed path**, because a block cannot learn the configurable
public prefix. They are anonymous and `GET`/`HEAD` only, take the tenant from the public binder (no
tenant is a 404), and a malformed query is the module's `{"detail", "code"}` 422. A signed-in visitor
gets the anonymous answer.

| Route | Answers |
| --- | --- |
| `/api/events/public/calendars?calendar=<slug>…&locale=` | the public calendars (all, or those named) and the categories a public event uses |
| `/api/events/public/upcoming?calendar=<slug>…&category=<slug>&count=&locale=` | the next public occurrences, at most `count` |
| `/api/events/public/occurrences?…` | the same answer as `/events/api/occurrences` |

Calendars and the category are **slugs**, resolved on every request (an old slug of a renamed
calendar resolves through its redirect). No calendar means every public calendar. A selection that
resolves to nothing is *nothing*, never every calendar, and a category that is not a public one
matches nothing. A calendar that stopped being public is dropped without a trace: no error and no
name. No answer carries an event's id.

| Limit | Value | Constant |
| --- | --- | --- |
| Public blocks path | `/api/events/public` | `PUBLIC_BLOCKS_API` |
| Events per upcoming answer (maximum / default) | 20 / 5 | `UPCOMING_BLOCK_MAX`, `UPCOMING_BLOCK_DEFAULT` |
| Calendars a block may name | 10 | `BLOCK_CALENDARS_MAX` |
| Cards one search returns, at most | 50 | `MAX_EVENT_SEARCH_LIMIT` |
| Matching events a search looks at, per kind | 50 | `CARD_SEARCH_SCAN` |
| Re-reads of series the occurrence cap left out | 3 | `CARD_READ_ROUNDS` |

An answer is cached for at most `min(public_cache_seconds, 60)` seconds, and as `private` with the
tenant in `Vary` whenever the tenant was picked by the request.

## The blocks

`UpcomingEvents` and `EventsCalendar` are contributed to pagebuilder's palette by
`sm_events/pagebuilder-blocks.ts` (group "Events", page-only). They need the optional
`pagebuilder` extra; events installs, boots and serves without it, and a host without pagebuilder
never imports the file. Pagebuilder on a host **without events** still renders a page that holds
one: the block draws nothing, the blocks around it render, the editor's canvas shows Puck's own
"No configuration for UpcomingEvents", and the stored props survive untouched.

**Request time, no snapshot.** A block stores only its settings and fetches in the visitor's
browser. Nothing about an event is frozen into the page, so making an event or a calendar
non-public takes effect on the next request, bounded by the short cache above. A block's language
is the page's, never a field of the block.

| Block | Props |
| --- | --- |
| `UpcomingEvents` | `heading` (up to 200 characters), `calendars` (slugs, up to 10), `category` (slug or empty), `count` (1 to 20, default 5), `layout` (`list` or `cards`), `showImages` (cards only) |
| `EventsCalendar` | `calendars` (slugs, up to 10), `defaultView` (`month`, `week`, `day`, `list`), `height` (`compact` 480, `medium` 640, `tall` 800 pixels) |

Each item shows its date and time on the event's own clock, its title linked to the event page,
the place, a marker for a cancelled or rescheduled occurrence and, in cards, the summary and
image. A title in another language than the page's is marked. While loading, when there is nothing
to show and when the fetch fails, a visitor sees nothing at all; the editor sees a hint ("no
upcoming public events", "1 chosen calendar is not public or no longer exists", without naming
it). `EventsCalendar` is the console's `Calendar` read-only, in a chunk of its own, so FullCalendar
loads only on a page that has one. Stored settings are normalised when a page is opened in the
editor and bounded again when rendered and by the server.

A bundle or restore carries the settings as they are: restored on another host, a block shows that
host's public calendars with those slugs, if any, and otherwise nothing.
