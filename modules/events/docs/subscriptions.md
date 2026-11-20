# External calendar subscriptions

A calendar can show the events of **another calendar** read-only: a holiday calendar, a
colleague's published calendar, an intranet room booking. The calendar's owner (or an events
manager) adds the address of an `.ics` feed in the **Subscriptions** dialog on the Calendars
screen. The events appear on that calendar marked **External**, with the subscription's name, and
nowhere else.

## What an external event can never do

- It is **plain text**: a title, a time, a place and a link, no description, attendee, organiser,
  alarm or attachment. The link is shown only if the feed gave a web address (`http` or `https`),
  and opens in a new tab with `noopener noreferrer nofollow`.
- It is **read-only**: no edit, move, "remind me" or registration control exists for it.
- It is **never re-published**: not in this site's `.ics` feeds (public, private links or a
  single event), not in the sitemap, the server-rendered pages or the JSON-LD, not as a newsletter
  card, never in a reminder. The one public surface that can show it is the public grid's API
  (`/events/api/occurrences`) and only for a subscription marked *Show on the public site*, on a
  public calendar, by someone holding `events.publish`. The pagebuilder calendar block leaves it
  out. Subscribing to this site's own feed is refused.
- It is **not an event**: it has no owner, revision, workflow or bus event, and the feed's `UID`
  is an opaque key inside its subscription.

## Using it

| Action | What happens |
| --- | --- |
| Add | The address is checked (see below), stored encrypted and shown only as `https://host/…`. The first refresh runs at once on a host with Celery eager, otherwise on the next beat tick. |
| Refresh now | Allowed once every 5 minutes per subscription and while no fetch is running; the screen shows the result as the subscription's status. |
| Edit | Change the name, colour, interval or visibility; type a new address to replace the old one (the field starts empty and the address is never shown again). A new address is due again after the minimum interval. |
| Pause / Resume | A paused subscription is not fetched and keeps showing what it has. A stopped one (ten failures in a row, or the server said *gone*) resumes once. |
| Remove | Final: the stored address is overwritten and the cached events are deleted in the same transaction. |

The address is a credential (private calendar links carry a token in the path or query): treat it
like a password. It is never returned by the API, logged, put in an error, a bus event or a
revision.

## How a fetch is made

Only through `sm_events.feeds.subscriptions.fetch` (never an `httpx.AsyncClient`, whose request log
would print the address). A fetch:

1. judges the address by the policy below, **resolves the name itself** and refuses unless
   **every** address is publicly routable;
2. connects to the exact address that was checked (no second lookup anywhere below), with the
   original name as `Host` and SNI and the certificate verified against that name;
3. sends only `Host`, `User-Agent: SimpleModule-Events/<version>`, `Accept`,
   `Accept-Encoding: identity` and, on the first hop, `If-None-Match` / `If-Modified-Since`: no
   cookie, no credentials, never a proxy from the environment;
4. follows at most three redirects **by hand**, each one through the full policy again, never
   from `https` to `http`;
5. reads the raw body to the size cap (a bigger declared length is refused before reading, an
   encoded body is refused so nothing can inflate past the cap), under one absolute deadline;
6. hands the body to the import's bounded scanner and mapper (the only `.ics` parser in the
   module), and replaces the subscription's events in one transaction only if all of it was read.

### The address policy

Checked on save **and** on every fetch and redirect hop (DNS can change). `https` only, no user
name or password, the default port, and a host name or a public IP literal (`2130706433` and
`0x7f.1` are refused). Save judges the address **without any lookup**, so a private literal and an
unreachable name answer alike; the name is resolved only in the worker and the outcome arrives as
the subscription's status, as one code from a closed set with no address, body or timing.

These are always refused, whatever the setting: loopback, link-local (including the cloud
metadata addresses 169.254.169.254 and 169.254.170.2), unspecified, multicast, broadcast,
Alibaba's 100.100.100.200, Azure's 168.63.129.16, Oracle's 192.0.0.192 and the IPv6 metadata
ranges (`fd00:ec2::/32`, `fd00:c1::/32`, `fd20:ce::254`), every IPv6 form that embeds one
(IPv4-mapped, NAT64, 6to4, Teredo) and any unique-local address whose low 32 bits are one of
those IPv4 addresses. The list is best-effort.

### The intranet switch

`allow_private_subscription_urls` (a system setting, off by default; only someone with
`settings.edit` changes it, never a calendar owner) lets a subscription use `10/8`, `172.16/12`,
`192.168/16`, `100.64/10`, `198.18/15` and `fc00::/7`, plain `http` and any port. **A subscription
may use it only if its saver held `events.manage` when the address was saved**; the flag is stored
per subscription, cleared when someone without that right changes the address, never taken from a
request, and stays when the saver later loses the permission until the address is edited. It is
applied at every fetch and redirect hop together with the setting (the setting off always wins).
A public subscription is never an internal one: turning one public deletes everything it stored from an internal address and fetches again under the public policy, and a fetch that started under another policy (public, internal access or the address changed meanwhile) stores nothing. With the switch on, anyone who may add a
subscription and holds `events.manage` can make the server send GET requests to internal http(s)
addresses, including services on its own private address, and see whether the answer parses as a
calendar: turn it on only for trusted networks. The server's own addresses are not listed.

## Refresh, backoff and the worker

`events.refresh_subscriptions` runs every minute on the `events` queue (it needs beat; a host
without one refreshes only when asked). One tick lists the oldest due subscriptions of every
tenant (round-robin, starting at a different tenant each minute), claims each with one
compare-and-set (a lease), fetches with no database session open and stores fenced on the lease.
A worker needs `SM_SECRET_KEY` (or the stored key) to open an address; with none it fetches
nothing and records nothing against the feeds.

| Limit | Value | Constant |
| --- | --- | --- |
| Whole fetch, every hop | 30 s | `SUBSCRIPTION_FETCH_SECONDS` |
| One name lookup | 5 s | `DNS_TIMEOUT_SECONDS` |
| Connect | 5 s | `FETCH_CONNECT_SECONDS` |
| One read | 15 s | `FETCH_READ_SECONDS` |
| Redirects followed | 3 | `SUBSCRIPTION_MAX_REDIRECTS` |
| Addresses tried per hop | 4 | `MAX_ADDRESSES_PER_HOP` |
| Address length | 2,000 | `SUBSCRIPTION_URL_MAX` |
| Name length | 100 | `SUBSCRIPTION_LABEL_MAX` |
| Events kept per subscription | 5,000 | `SUBSCRIPTION_ITEMS_MAX` |
| Events kept per tenant | 50,000 | `SUBSCRIPTION_TENANT_ITEMS_MAX` |
| Subscriptions per calendar | 10 | `SUBSCRIPTIONS_PER_CALENDAR` |
| Subscriptions per tenant | 100 | `SUBSCRIPTIONS_PER_TENANT` |
| Refresh interval, shortest / longest | 15 / 1,440 minutes | `SUBSCRIPTION_MIN_REFRESH_MINUTES` / `SUBSCRIPTION_MAX_REFRESH_MINUTES` |
| Refresh now, per subscription | 300 s | `SUBSCRIPTION_REFRESH_NOW_SECONDS` |
| Failures in a row before it stops | 10 | `SUBSCRIPTION_MAX_FAILURES` |
| Longest backoff and longest honoured Retry-After or max-age | 24 hours | `SUBSCRIPTION_MAX_BACKOFF` |
| Fetches per tick | 20 | `SUBSCRIPTION_TICK_FETCHES` |
| Bytes received per tick | 50 MiB | `SUBSCRIPTION_TICK_BYTES` |
| Seconds per tick | 45 s | `SUBSCRIPTION_TICK_SECONDS` |
| Lease | 2 minutes | `SUBSCRIPTION_LEASE` |
| Simultaneous fetches, install-wide / per tenant | 8 / 2 | `SUBSCRIPTION_MAX_CONCURRENT_FETCHES` / `SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT` |
| Deleted subscriptions kept | 30 days | `SUBSCRIPTION_DELETED_KEPT_DAYS` |

The interval is the subscription's own or `subscription_refresh_minutes` (default 60), kept
between 15 and 1,440 minutes and jittered by 10 %. A server's `Cache-Control: max-age` and
`Retry-After` are believed (never shorter than our interval, never beyond a day). A failure backs
off exponentially (interval x 2^(n-1), at most a day). The **lease** must outlive a fetch's total
timeout by a margin and no more, so a hung fetch frees its slot soon after it is cut off; the
install-wide and per-tenant caps keep one tenant's hung feeds from holding every slot.

## Failure codes

Shown translated, never as a message from the server: `url_invalid`, `url_scheme`,
`url_userinfo`, `url_port`, `url_unreachable` (a refused or missing host, one answer), `url_own_feed`,
`url_unreadable` (the stored address no longer opens: the key was rotated away; enter it again),
`too_many_redirects`, `insecure_redirect`, `timeout`, `connect_failed`, `tls_failed`,
`http_status` (with the server's number), `gone` (stops at once), `too_large`,
`unsupported_encoding`, `unexpected_content_type`, the scanner's own (`ics_invalid`,
`ics_encoding`, `too_many_events`, `file_too_large`, `too_many_lines`, `line_too_long`,
`too_many_components`, `too_deep`, `too_many_timezones`, `component_too_large`, `too_complex`) and
`internal`. A feed that fails keeps its previous events. Events the mapper skips (an unknown time
zone, an unsupported repeat rule) are counted by reason on the screen.

## Secrets and rotation

The address is stored only as `enc:v2:` ciphertext (`events_subscription.url_enc`) under the key
derived from `SM_SECRET_KEY` for `sm_events`; `scripts/reencrypt_secrets.py` rewrites it across
every tenant during a rotation ([rotating the key](../../../docs/secret-key-rotation.md)). After a
rotation without the old key in `SM_SECRET_KEY_PREVIOUS` it reads `url_unreadable` and the
subscription stops until its address is entered again.

## Tests make no real network connection

The unit tests use a fake resolver and a faked connection layer; one suite runs the whole path
over a real **loopback TLS socket** with a throwaway CA injected through the transport's trust
seam, with the guard widened to loopback inside that test only. The fetcher always refuses
loopback, so **the browser suite does not exercise a live fetch**: its external entries are written
by `tests/e2e/support/seed_external.py` through the module's own store function.
