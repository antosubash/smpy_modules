# Operating the public surface

## Settings (Settings screen, SYSTEM scope)

| Setting | Meaning |
| --- | --- |
| `public_prefix` | Where the public pages mount (default `/events`). **Needs a restart.** One path of lower-case letters, digits and hyphens. A value that is empty, starts with a framework path (`/api`, `/admin`, `/users`, `/static`, ...), starts with another module's public prefix (news' `public_route_prefix`, read from its settings) or with a content-language tag is **ignored** with an error in the log, and `/events` is served. |
| `public_title` | What the site calls its events: the index page's title and the name of `calendar.ics`. Applies at once. |
| `public_cache_seconds` | How long a browser or cache may keep a page, feed or sitemap (default 300; the index, calendar pages and the occurrences API at most 60). `0` sends `no-store`. |
| `content_locales` | Languages events are published in (needs a restart); the first is the default. |

## Caching

Anonymous pages are `public` and revalidate with a weak `ETag`, only when no tenant was picked by
anything request-specific and the host is single-tenant. Otherwise they are `private`, and `Vary`
names `Cookie` and the tenant header. A signed-in visitor's page is `private, no-store`. Every
response that names the origin adds `Host` to `Vary` until the host's `public_base_url` is set. **Production must
set it** on a single-tenant host (the startup log warns): without it, canonical, `og:url`, `hreflang`, feed
and sitemap URLs follow the client's `Host` header, which anyone can choose. The framework sends a fresh session
cookie on every anonymous response, so a CDN will not cache these pages until that is fixed
upstream; browsers and private caches do.

**An unpublished event can outlive its unpublishing in a shared cache.** An event page is cached
`public, max-age=300` on a single-tenant host (feeds and the sitemap the same; the index, calendar
pages and the occurrences API at most 60 seconds), so a CDN or proxy in front may keep serving an
event for up to five minutes after the origin stopped (the origin answers the 404 at once). To
shorten it, lower `public_cache_seconds` on the Settings screen (`0` is `no-store`, which also
drops the `ETag`), or purge the event's address (and `/events/`, the calendar page, `calendar.ics`
and `sitemap.xml`) from the cache when unpublishing something urgent.

A `304` carries `ETag`, `Cache-Control` and `Vary` and, on the framework 0.0.44 host, no
`Content-Security-Policy` (pinned by `host/tests/test_events_wiring.py`).

A scheduled publish becomes visible on the next request, but a cached page or feed may lag by up to
`public_cache_seconds`.

## Feeds

- The time zone definitions in a feed list explicit transitions for the current year and the **20
  years after it** (or to the end of a bounded series). A client expanding an open-ended series past
  that horizon applies the last offset. The file changes once a year, not daily, so `ETag`s are stable.
- A feed is capped (see [Public pages](public.md#subscribing)); `X-Events-Truncated: 1` says it was cut.
- Text is stripped of control characters on the way in; the library escapes and folds lines.
- `.ics` and `sitemap.xml` are limited to 60 requests a minute per IP and the occurrences API to 120,
  on top of the host's `rate_limit_public` for pages.

## Sitemap and robots.txt

The sitemap is at `{public_prefix}/sitemap.xml` (default language prefix only). Neither pagebuilder
nor news has a registry for another module's sitemap, so add the line to the site's `robots.txt`
yourself: `Sitemap: https://example.org/events/sitemap.xml`.

## A fresh install

Until the first-run setup wizard is complete the framework redirects **every** request, public pages
included, to `/setup`.

## Extra checks

`host/tests/test_events_wiring.py` boots the real host and checks the routes, the anonymous
exemption (`GET`/`HEAD` only), the rate limits and the 304. `tests/web/public/test_leaks*.py` is the
leak harness: every public route is in its table, and a route that is not fails a test.

## Subscriptions to internal calendars

`allow_private_subscription_urls` (off by default) is a system setting: only someone with
`settings.edit` changes it, never a calendar owner. With it on, a holder of `events.manage` can
subscribe a calendar to `http(s)` addresses in 10/8, 172.16/12, 192.168/16, 100.64/10, 198.18/15
and fc00::/7, on any port. That means the server will send GET requests to internal services,
including services bound to this server's own private address, and the subscriber learns whether
the answer parsed as a calendar. Loopback, link-local, multicast and the cloud metadata and
control endpoints (169.254.0.0/16, 100.100.100.200, 168.63.129.16, 192.0.0.192, fd00:ec2::/32 and
every IPv6 form embedding one) are refused whatever the setting says. The user-visible failure
codes are the same closed set either way. Turn it on only if an intranet calendar server needs it.
