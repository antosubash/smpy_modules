# Tracking and reports

Opens and clicks are counted per campaign, and a report screen
(`/admin/newsletter/campaigns/{id}/report`, `newsletter.view`) shows them.

## What is stored

Per recipient (`newsletter_send`): the time of the first open, an open count,
and the time of the first click. Per recipient and link (`newsletter_click`):
the time of the first click and a count. Per campaign: counters. **Nothing
else.** No IP address, user agent, location, device or mail client is stored,
and the two routes never read `request.client`, `User-Agent` or any
`X-Forwarded-*` header, and log nothing about the request. A failed write logs
the send id, never the token. Retention: the rows live as long as the campaign
(unscheduling a campaign deletes its links and their clicks).

## How the pixel and the links are built

The render snapshot holds `{{open_pixel}}` and `{{link:N}}` placeholders; the
worker fills them per recipient when it composes the message, **before** the
merge fields, so recipient data can never add or multiply one. Scheduling
writes one `newsletter_link` row per distinct URL, numbered from 1 in order of
first appearance (a card's image, title and "Read more" share one).

- Only the HTML part is tracked, and only `<a href>` values that are `http(s)`
  with a host. Never rewritten: the unsubscribe link, `mailto:`, the module's
  own `/newsletter/` routes and image `src`s.
- **The text part is untracked**: a click from a text-only client is not counted.
- At most 100 distinct links, each at most 2000 characters (`is_http_link`'s
  limit). Beyond either, the link stays as written and `prepare` logs one
  WARNING naming the campaign.
- Previews and test sends carry no placeholders and are never tracked.

The click path carries the link's position, never a URL: `/newsletter/c/{token}/{N}`
redirects (302) only to that campaign's own stored `newsletter_link` URL, URI-encoded
(the `Location` is the stored URL with any character not legal in a URI
percent-encoded, so `ü` becomes `%C3%BC`). `N` is written as `prepare` writes
it (1 to 100, `MAX_TRACKED_LINKS`), with no leading zero; the route accepts one
to three digits and any other spelling, like any other path under
`/newsletter/c/`, gets the same fixed 404.

## The token

A message carries up to three tokens (an open or click token only while that
kind of tracking is on), `{tenant}.{campaign}.{send}.{mac}`, each an
HMAC under the host secret bound to a purpose: `u` (unsubscribe), `o` (open),
`c` (click). A token minted for one purpose fails the other two routes, so a
click URL leaked from a history or proxy log cannot unsubscribe anyone. Tokens
are never stored.

The tenant comes from the verified token. A request's tenant can refuse a
token only when it is **host-derived** (`tenant_source` `subdomain` or
`fixed`), as on the unsubscribe route: a signed-in member of another
organisation on the apex never blocks a reader's click or pixel.

| Request | Pixel `/o/{token}.gif` | Click `/c/{token}/{N}` |
| --- | --- | --- |
| MAC fails (incl. another purpose), `test`, malformed | GIF, nothing written | 404, fixed body |
| Verifies, host resolved another tenant | GIF, nothing written | 404, fixed body |
| Verifies, no link at `N` | n/a | 404, fixed body |
| Verifies, link exists, no such send | GIF, nothing written | 302, nothing written |
| Verifies, tracking on | GIF, counted | 302, counted |
| Verifies, tracking off for that kind | GIF, nothing written | 302, nothing written |

A wrong-purpose token opens no database session. Recording failures roll back
and still answer the GIF or the 302. Both routes send `no-store`. They also
ask for `Referrer-Policy: no-referrer`, but the framework's security-headers
middleware (`simple_module_hosting`) replaces it with the host-wide
`strict-origin-when-cross-origin`. The token is still safe: a cross-origin
redirect target receives only this site's origin, never the path that holds
the token.

## Switching tracking off

`tracking_opens` and `tracking_clicks` (Settings, system-wide) default to on.
Off **composition**: new messages carry no pixel or no rewritten links from the
next dispatch tick (about 60 s, plus the settings cache of about 30 s); a tick
already running finishes with the settings it started with. Off **recording**:
applies at once, per request, so mail already delivered stops being counted
too. A click counts as an open only while open tracking is on.

## What the numbers mean

- **Opens are approximate.** Apple Mail Privacy Protection and image proxies
  load the pixel automatically, so opens can be inflated. A click also sets the
  first open if it is empty.
- **Clicks may include automated link scanners.** Neither is detected; without
  storing the IP and user agent it cannot be done honestly.
- **Accepted** is `sent_count`: the relay took the message. It is not
  "delivered"; only synchronous bounces are known.
- **Rates** are unique opens (clicks) from sends whose status is `sent`,
  divided by accepted, so a rate never passes 100 %. Engagement on an
  outcome-unknown send, or one that arrives before acceptance, counts only in
  the **"all messages"** totals (every send, from the campaign counters). With
  accepted = 0 the rate shows a dash. The campaign list's open and click
  percentages use the same numbers (`CampaignListItem` carries the accepted
  counts; the campaign detail does not).
- **Timeline.** First opens and first clicks in UTC calendar buckets: hourly
  for the first 72 hours (at most 72 buckets), then daily for at most 90 days.
  The window is `[start, start + n * bucket)` with an exclusive end; events
  outside it count in the totals only. Labels are UTC.

## Rate limits

Per IP, `GET` only: 600/minute on the pixel (image proxies share egress IPs)
and 300/minute on the click. Both prefixes are public with these as their
anonymous rate, replacing the host's `rate_limit_public`, and the same rules
apply to signed-in callers. Unique counts cannot be inflated by replaying a
token; a forged token costs one HMAC and no query.

## Operator note

The host's access log records request paths, which include the open and click
tokens, as it already does for `/newsletter/u/`. Point log retention at it; see
[`operations.md`](operations.md).
