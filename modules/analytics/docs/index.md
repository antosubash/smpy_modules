# Analytics

Install `simple_module_analytics[geoip]` in a consuming host. The base package
works without GeoIP dependencies and shows location as unknown. This demo host
includes the GeoIP extra. Run host migrations before starting the app; migrations
belong to the consuming host, never to this wheel.

## Start collecting

Open **Analytics**, create a property, add the exact origin (`https://example.org`)
and the routes to track, then enable it. A new property is paused and has no
routes. Public and application properties are separate opt-ins. Use one per
traffic audience; overlapping properties intentionally each count a visit.

Patterns match the entire pathname. `:name` matches one nonempty segment. For
example `/p/:slug`, `/de/p/:slug`, `/news/:slug` or `/records/:id`. Add each language
prefix explicitly. Application paths are stored as the matched pattern; public
paths retain their slug. All query parameters and fragments are removed. Only
UTM parameters individually enabled on the property are accepted. Auth, login,
logout, register, settings and analytics path segments are excluded even if a
pattern includes them. Analytics stores no titles, form contents or user IDs.
Choose public route slugs and allowed event values accordingly: these fields can
still contain personal information supplied by an application.

The demo host installs the adapter in its Inertia entry point. Other hosts import
`startHostAnalytics` from `@simple-module-py/analytics`, passing a subscription that
forwards completed Inertia navigation URLs (skip Inertia's `initial` event; the
initializer handles initial load). Call its returned cleanup on teardown. The
module also exports `initAnalytics(config, url)` and `track(name, properties)` for
explicit integration. Configure allowed event/property names first:

```ts
import { track } from '@simple-module-py/analytics';
await track('download', { format: 'pdf' });
```

An event named `download` with property `format` must be declared on the property.
Other properties are discarded. Event names are 1–50 characters; up to 20 scalar
string/number/boolean values are accepted, with strings limited to 500 characters.
Requests are limited to 8 KiB. Collection retries and offline replay are disabled.

## Export a report

Choose a property, UTC date range and filters, then select **Export CSV** after
the report finishes loading. The download contains the applied property and
filter scope, four totals, daily pageview/event counts and every returned
breakdown row (up to 50 per dimension, including approved event properties).
Dates are inclusive UTC. Visitors and sessions retain the estimates described
below. Empty filters are recorded as `All`; unknown geographic values are
recorded separately as `Unknown`.

The CSV uses stable English column names and includes Unicode labels. Text that
could be interpreted as a spreadsheet formula is prefixed with an apostrophe.
This exports the currently loaded authorized report locally, without another
server query. It excludes the separate five-minute recent-activity list and is
not an export of every stored event. Export is unavailable during loading or
after an error; refresh successfully before trying again.

## Country, region and city

Provision an official GeoLite2 City MMDB file separately from the Python package.
Use [MaxMind's updater](https://dev.maxmind.com/geoip/updating-databases/) with its
credentials stored in the deployment's secret management, outside this repository.
Do not upload or commit the production database or credentials. Mount the MMDB
read-only at an absolute path available in every web process, then configure:

```sh
uv run python scripts/set_setting.py sm_analytics geo_database_path /srv/geoip/GeoLite2-City.mmdb
```

The path and `geo_enabled` apply at runtime. Each process reopens an atomically
replaced database automatically. The status screen shows availability and age;
older than 30 days is marked stale. Missing, corrupt or unavailable data yields
unknown locations without blocking collection. No historical re-geolocation runs.
Country and subdivision codes and city GeoNames IDs identify filters; names are
labels. Geographic report values are approximate network locations, not GPS.
Private/reserved addresses and unmatched records produce unknown values. No IP
is sent to a lookup service and neither addresses nor coordinates are stored.
Trust client addresses only through the host's configured trusted proxies; never
trust an arbitrary `X-Forwarded-For` or country header. Application server logs
are governed separately by the host logging configuration.

## Metrics, access and retention

All times and dates are UTC. Visitors are daily estimates from a property/tenant/
date-scoped HMAC of the trusted client address and browser family. There are no
cookies, persistent browser IDs or cross-day profiles. Shared networks may merge
people and network/browser changes may split them. Sessions end after 30 minutes
of inactivity or UTC midnight. Custom events contribute to visitor/session counts;
pageviews and custom events are separate totals. Known bot/crawler/spider agents
are omitted; this is not comprehensive bot detection. DNT and GPC opt out in both
tracker and collector.

`analytics.view` grants tenant reports; `analytics.manage` grants property writes.
The built-in screen needs view permission as well. Property IDs are public routing
identifiers, not secrets. Origin checks and rate limits reduce unwanted writes but
cannot prove an event came from a real browser. There are no public report links.

Reports support inclusive start/end dates (default last seven days, maximum 366),
path/event/geographic filters, top-50 breakdowns and the last five minutes of
activity. Select an event to see its allowed property breakdowns. Selecting an
unknown location filters empty values; leaving a selector at All does not filter.
Recent activity refreshes every 30 seconds while visible. No map or GPS is used.

Retention defaults to 90 days. Every minute each web process deletes at most 5000
expired events per tenant, then removes expired sessions with no remaining events.
Multiple replicas may safely run idempotent sweeps. Disable the restart-only
`scheduler_enabled` deployment setting when driving cleanup externally. A bounded
manual run uses the same stored retention value and existing host secret policy:

```sh
uv run python scripts/cleanup_analytics.py
```

A backlog may need repeated sweeps. Property deletion permanently removes its
events and sessions after confirmation in the screen; pausing keeps existing data.
Analytics settings are database-backed; `SM_ANALYTICS_*` variables have no effect.

## Query indexes

All report and collection predicates include a tenant. The host migration
`b6d4e2a0c913` adds indexes to match independently optional filters and the
property-independent retention sweep; consuming hosts must migrate their own
schema to match the module metadata.

| Statements | Index access |
| --- | --- |
| Property lookup, collection lock/update, property deletion | Property primary key; tenant is checked on the selected row |
| Property listing, enabled public configuration, scheduler tenant enumeration | Property `tenant_id` index; the small property list is sorted by name after filtering |
| Duplicate event lookup | Unique `(tenant_id, property_id, event_id)` constraint |
| Visitor's latest session and session deletion by property | `(property_id, tenant_id, visitor, last_seen)`; latest lookup scans backwards |
| Unfiltered totals, daily and ranked breakdowns, active visitors, recent events | Event `(property_id, tenant_id, created_at)`; recent events scan backwards |
| Standalone country, region, city, path or event-name filters | One event `(tenant_id, property_id, <filter>, created_at)` index per supported equality filter |
| Allowed JSON event-property breakdowns | Event-name/time index narrows the selected event; JSON extraction/grouping happens on those rows |
| Expired event/session candidate IDs, across every property in a tenant | Covering `(tenant_id, created_at, id)` / `(tenant_id, last_seen, id)` |
| Property foreign-key enforcement inside the database, without a tenant predicate | Existing event-time/session-visitor indexes now lead with `property_id`; no-match checks avoid unrelated histories |
| Session orphan check and session foreign-key enforcement | Event `session_id` index; the orphan query also filters tenant |
| Batched expiry deletion and property cascade deletion | Primary key for selected IDs; event/session property/tenant index prefixes for whole-property deletion |

Property IDs are globally unique. Leading with the property on the existing time
and visitor indexes supports both implicit foreign-key checks and explicit
queries that constrain both property and tenant; tenant-only cleanup keeps its
own time index.

Combined filters use a selective indexed prefix and check remaining conditions;
a separate index for every combination would multiply collection cost. The old
country/region/city hierarchy index is replaced because it cannot bound time
contiguously when intermediate location filters are absent. An empty Unknown
value uses the same equality index; All omits the predicate.

These indexes narrow matching rows; exact distinct counts, UTC date grouping,
JSON extraction and top-50 rankings still aggregate raw history. A wide report
may legitimately use a sequential scan, and ranking/date groups may need a sort.
No indexes are added on every displayed dimension or arbitrary JSON property.
Daily rollups remain the next step for consistently interactive long ranges.
Index creation uses normal transactional DDL and can block writes during a large
migration; allow maintenance time and additional disk space. Each collected event
also maintains the new indexes, so measure ingestion on the target deployment.

## Verification and capacity

Run `uv run pytest` from this module directory; set the repo's guarded
`SM_TEST_DATABASE_URL` to opt into a dedicated Postgres test database. Frontend
unit tests run through repository Vitest. `tests/e2e/analytics.spec.ts` is standalone.
A representative nine-million-event benchmark is opt-in; its results are specific
to the backend and hardware measured. Until measured on a deployment, 100,000
events/day is a design target, not a capacity guarantee.

A local 2026-11-08 benchmark reused synthetic nine-million-event histories on
SQLite and Postgres 16. The following compares the original index set with this
migration (seconds per complete service report):

| Backend | 7 days before / after | 90 days before / after | C1 committed events/s before / after |
| --- | --- | --- | --- |
| SQLite | 7.14 / 6.97 | 102.39 / 98.85 | 117.75 / 110.14 |
| Postgres | 3.93 / 4.33 | 55.62 / 55.94 | 120.72 / 123.02 |

After measurements use one report per range and 1000 individually committed
collector calls. Before report values are medians of three samples except the
Postgres 90-day report (one). Histories also contain 4000–5000 prior synthetic
collector events; these remain in after reports. Timings are cache-influenced,
local observations, not a statistically controlled throughput or capacity claim.
The SQLite write sample was about 6.5% slower; deployments must remeasure ingestion.

All analytics indexes, including primary/unique indexes, grew from 1.91 to
4.09 GB on SQLite and 1.42 to 2.24 GB on Postgres. Initial index additions took
104 / 149 seconds on SQLite / Postgres; rebuilding the two property-leading
indexes took another 20 / 18 seconds. Full migration time will vary. The fixture
uses short paths and mostly empty location codes, so other traffic can have larger indexes.
Selective filters and tenant-wide cleanup now have the intended range prefixes;
broad reports still aggregate raw history and show no material latency gain.
Daily rollups would be needed for consistently interactive long-range reports.
