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

## Verification and capacity

Run `uv run pytest` from this module directory; set the repo's guarded
`SM_TEST_DATABASE_URL` to opt into a dedicated Postgres test database. Frontend
unit tests run through repository Vitest. `tests/e2e/analytics.spec.ts` is standalone.
A representative nine-million-event benchmark is opt-in; its results are specific
to the backend and hardware measured. Until measured on a deployment, 100,000
events/day is a design target, not a capacity guarantee.

The initial SQLite measurement used nine million events (about 3.3 GB): a
seven-day full report took 7.8 seconds and a 90-day report took 104 seconds.
The collector measured 4.1 events/second in the restricted test environment,
which required periodic asyncio wakeups. These are local observations, not
production guarantees. Long-range reports scan raw history; daily rollups would
be needed for consistently interactive reports at this volume. Postgres was not
benchmarked.
