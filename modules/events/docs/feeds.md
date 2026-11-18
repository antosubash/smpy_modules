# Private feed links

A signed-in user can subscribe to any calendar they may view through a private link,
`/events/feed/<token>.ics`. It serves, on every request, what that user may see **now**:
the **published** events of that calendar (never drafts, even for someone who may write them),
and it stops the moment their access does.

## How a link is protected

- A token is `evf_` plus 32 random bytes. Only its SHA-256 is stored, and the token is shown
  once, when it is created. It is in no list, log line or error.
- The route binds the **tenant of the token's row**: the module's third documented tenancy
  exception, after newsletter's `/newsletter/u/{token}` and records' form token. Only a tenant
  the request's *host* resolved can refuse a link; one a visitor chose is ignored.
- A malformed, unknown, revoked, expired, other-tenant or wrong-host token, a deactivated or
  removed owner, a lost `events.view`, a removed share and a trashed calendar all answer one
  `404`, held back to a latency floor.
- Responses are `private, no-store`, with no `ETag` and no `304`.

## Operating notes

- **Referrer-Policy.** The route sends `Referrer-Policy: no-referrer`, but the framework's
  `SecurityHeadersMiddleware` (0.0.44) replaces it on every response with
  `strict-origin-when-cross-origin`. A feed is not a page and links nowhere, so the exposure is
  small, but the link is a credential: avoid putting it on pages. An upstream change is needed.
- **Logs.** A filter on the request, rate-limit, uvicorn and database loggers and on every
  handler that exists at startup rewrites `/feed/<token>` to `/feed/<redacted>`. A handler an
  operator adds later is covered when the filter is installed again, and reverse proxies, load
  balancers and CDNs log paths on their own: redact `/feed/` there.
- **Latency floor.** Every refusal is held to 0.25 s (`FEED_DENY_FLOOR_SECONDS`), so a refusal
  is not faster than an answer.
- **Limits.** 30 requests a minute per IP, and 20 per token in ten minutes, per process.
- **Revocation.** Revoking a link (yours, or any as a manager, "Everyone's links") sets
  `revoked_at`; the row is deleted by the janitor 30 days later (`FEED_REVOKED_KEPT_DAYS`). The
  next request gets the same `404` an invented token gets, byte for byte. A user's links
  also stop when they are deactivated or lose `events.view`; they are not deleted, so regaining
  the right revives them.
- **Throttle is per process.** The per-token count lives in memory (at most 10,000 keys), so with
  N workers the real ceiling is N times the figure above. The per-IP limit is the framework's.
- **At most five links** per user and calendar; a sixth is `token_limit`.
- **Where the link is shown.** The Subscribe dialog shows a new link once; the page never holds a
  stored token again, only its label, language and dates.
