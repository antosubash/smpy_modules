# Campaign content

How a campaign body is stored, sanitised and rendered to email. Everything the
recipient's mail client receives is produced by `sm_newsletter.content.render`;
nothing else builds newsletter HTML.

## The body

A campaign body is a list of Puck `content` items, `[{"type": ..., "props":
{"id": ..., ...}}]`, at most 200, with unique ids. Puck's `root` is not stored.
`sm_newsletter.content.blocks.parse_body` validates it on every write and again
when a stored draft is rendered. Unknown block types and unknown props are
refused (`422 invalid_body`); the error names the path (`body[2].props.href`)
and never echoes the input.

| Block | Props | Notes |
| --- | --- | --- |
| `Heading` | `text` (1-200), `level` 1 or 2, `align` left/center | Plain text; no control characters |
| `RichText` | `html` (at most 20000) | Re-serialised from an allow-list, see below |
| `Image` | `src`, `alt`, `href`, `width` (1-600) | `src` is a URL, never an upload |
| `Button` | `label` (1-80), `href`, `align` | Takes the branding accent as its colour |
| `Divider` | none | |
| `Spacer` | `size` sm/md/lg | |
| `ArticleCard` | card snapshot | News article, see Cards |
| `PageCard` | card snapshot | Pagebuilder page, see Cards |

The layout is one 600 px column of nested tables with inline styles, so it holds
in clients that ignore `<style>`. A fixed header (logo or app name) and a fixed
footer wrap the blocks; the editor cannot remove either.

## URLs

`sm_newsletter.content.urls` decides what a link or image may point at:

- Links (`Button.href`, `Image.href`, rich-text `a[href]`, card `url`): `http(s)`
  with a host, `mailto:`, a site path starting with a single `/`, or exactly the
  `{{unsubscribe_url}}` tag. At most 2000 characters, no whitespace or control
  characters, no backslash, no `{{`.
- Images (`Image.src`, card `image_url`): empty, `http(s)`, protocol-relative
  with a host, or a site path. Same length and character rules.
- No file upload in this release. File-storage downloads are permission-gated,
  so an uploaded image would be broken in every inbox. The image picker lists
  pagebuilder's raster media (never `image/svg+xml`) and stores its URL.

Stored values stay as typed (a site path stays a site path); the renderer makes
them absolute, so a later change of origin still works. There are two origins:

- **Content links** (images, buttons, cards, rich-text links) are made absolute
  against the *campaign tenant's* public origin (`content_base`). On a
  multi-tenant host with `tenants.subdomain_base` that is
  `<scheme of public_base_url>://<org slug>.<subdomain_base>[:port]` (the
  framework has no helper for an organisation's canonical origin as of 0.0.42);
  otherwise the host's `public_base_url`. Identical slugs in two tenants render
  two different addresses. Never the request `Host`.
- **Newsletter's own routes** (unsubscribe link, logo) use `public_base_url`
  (`public_base`), because their tenant comes from the token.

With either base blank, the preview renders relative URLs and warns
`relative_urls`; a test send is refused with `422 public_base_url_required`.
Render warnings are `relative_urls`, `physical_address_missing` and
`empty_body`.

## Rich text

`sm_newsletter.content.richtext.clean` parses with the standard library's
`HTMLParser` and *builds* its output; nothing is filtered through. It emits only
`p br strong em u s a ul ol li blockquote` (`b` becomes `strong`, `i` becomes
`em`), keeps no attribute but `a[href]` (which must pass the link rule; a
duplicate `href` keeps the first), and escapes all text. The contents of
`script style iframe object embed template svg math head title noscript` are
dropped; any other tag is unwrapped and its text kept. Nesting is capped at 20.

It runs at save (the stored value is the cleaned form) and again at render, so a
row written around the API is still safe. The admin preview is an
`<iframe sandbox="" srcDoc>` as a second layer. Headings, code and anything else
Puck's editor could produce outside the list are flattened to text.

## Merge fields

| Field | Becomes |
| --- | --- |
| `{{first_name}}` | The subscriber's first name, escaped; empty when unknown |
| `{{first_name\|fallback}}` | The name, or `fallback` (at most 100 characters, no `|`, `{`, `}`, `<`, `>`) |
| `{{unsubscribe_url}}` | The recipient's unsubscribe address |

Any other `{{` or `}}` in a heading, button label, image alt text or rich text
is refused at save (`invalid_body`), and so is one in the subject or preheader
(`invalid_campaign`, naming the field). `render` runs once per campaign and leaves
the tags in; `personalise` fills them per recipient.

A **preview** and a **test send** have no send row and no MAC, so
`{{unsubscribe_url}}`, the footer link and the `List-Unsubscribe` header all point
at `<public_base_url>/newsletter/u/test`
(`constants.TEST_UNSUBSCRIBE_TOKEN`). The unsubscribe page (PR 4) must answer
that token like a forged one. Tracking is never added to a preview or test send.

## Footer and branding

The footer states why the recipient got the message (`newsletter.email.footer_reason`
with the app name), prints the `physical_address` setting, and links to
unsubscribe. Its strings come from the `newsletter.email.*` catalogue keys in the
host's `i18n_default_locale`, falling back to the package's `en.json`; a
per-campaign or per-subscriber language is PR 4's call.

Branding is the **system** theme (`app_name`, `primary_color`, `logo_file_id` from
the framework's branding module), never a tenant's override: the sender identity
is install-wide, and PR 4's worker has no request. Without branding the name is
`from_name` (or "Newsletter") and the accent is `#2563eb`. The logo is
`<public_base_url>/newsletter/brand/logo?v=<logo_file_id>`, an anonymous route
that serves the system-scope logo explicitly (404 when there is none).

## Cards

Article and page cards are **snapshotted when inserted**, server side:
`POST /api/newsletter/cards/snapshot {kind, source_id}` returns the props, read
through `news.contracts.articles` or `pagebuilder.contracts.cards` and nothing
else. The email then renders from the snapshot, so a later edit or unpublish of
the article does not change a draft until the editor presses Refresh
(`POST /api/newsletter/campaigns/{id}/cards/refresh {block_id,
expected_revision}`). A source that is now unpublished, trashed or gone answers
`409 card_source_gone` and the snapshot is kept.

`news` and `pagebuilder` are optional extras. `content/integrations/` is the only
package that imports them, each import deferred and guarded; a capability is
available only when the package imports *and* the module is mounted. When one is
missing, the editor still defines both card blocks (an existing card stays
visible, deletable and rendered from its snapshot) but moves them to a hidden
palette category, disables the picker and Refresh with a note, and the server
answers the card, media and refresh routes with `409 integration_unavailable`.

## Campaigns

Drafts only in this release (`status = draft`); audience is `all`
(`segment:` and `tag:` get `422 audience_unsupported`).

- **Revision.** `newsletter_campaign.revision` is an integer. PATCH and Refresh
  require `expected_revision`; the write is one conditional `UPDATE ... SET
  revision = revision + 1 WHERE id, tenant_id, status = 'draft', revision`.
  Zero rows: `409 stale`, or `409 not_a_draft` once the status is re-read.
  Delete is conditional on draft the same way. The editor autosaves with a 1.5 s
  debounce and flushes pending edits before Refresh.
- **List access on every request.** `campaigns/access.py` checks
  `can_read_list` (through `sm_records.contracts.newsletter`, with
  `caller_roles(request)`) for the campaign's list on read, list (campaigns on
  unreadable lists are filtered out), patch, delete, preview, refresh and test
  send. An unreadable list answers 404, so existence does not leak. Choosing an
  unreadable list is `403 list_forbidden`; an unknown one `422 unknown_list`.
- **Header inputs.** Subject, from name, reply-to and the settings that become
  headers refuse CR, LF and other control characters (`core/headers.py`) at
  write, and are checked again before the send ledger admits an attempt.

## Preview

`GET /api/newsletter/campaigns/{id}/preview` renders the saved campaign
(`newsletter.view`); viewers and non-drafts use it.
`POST /api/newsletter/preview` renders unsaved content and is used only for
editable drafts by `newsletter.edit` holders. Both render with no recipient and
the test unsubscribe link.

## Test send

`POST /api/newsletter/campaigns/{id}/test-send {recipients}` (`newsletter.send`),
at most 5 addresses, subject prefixed `[TEST] `, no recipient name, the test
unsubscribe link, with `List-Unsubscribe`, `List-Unsubscribe-Post` and
`Precedence: bulk` so an operator can check the DKIM `h=` list.

Order of events: the campaign lookup, the cancelled check, the sender
configuration, the header inputs and the render all happen **before** the lock,
so a 404, 409 or 422 never waits behind the dispatcher. Then, inside the
install-wide dispatch lock (`sending/lock.py`: a Postgres advisory lock, or the
`newsletter_dispatch_lock` lease row on SQLite, with a 120 s lease; not acquired within 15 s is
`409 dispatch_busy`):

1. The header values are re-checked.
2. **Admission is all-or-nothing.** The rolling 24 h and 60 s windows are counted
   from `newsletter_send_attempt` across every tenant (`pending`, `accepted` and
   `unknown` count; `rejected` and `failed` do not). If `used + n` exceeds
   `daily_limit` or `per_minute_limit`: `429 send_budget_exhausted`, nothing sent
   and **no attempt rows written**.
3. The transport session opens (an unreachable relay is `502
   transport_unavailable`, before any row).
4. Per recipient: renew the lease, commit one `pending` attempt row, make the SMTP
   call, then close the row with the outcome.

A row that never resolves (a crash) stays counted for its window. Outcomes per
recipient: `accepted`, `rejected` (a refusal at MAIL/RCPT/DATA; the session issues
`RSET` before the next recipient), `unknown` (the body was sent and the answer was
lost or malformed) and `failed` (a known pre-acceptance failure, such as a
connection lost or a timeout before DATA; retryable, the session reconnects).
The `console` transport logs instead of sending and keeps a per-tenant capture
(the last 50 messages of each tenant) that
`GET /api/newsletter/outbox` (`newsletter.manage`, `console` transport only)
returns.

## Goldens

The renderer's byte-exact snapshots are `tests/content/golden/<case>.html` and
`<case>.txt` (`minimal`, `kitchen_sink`, `no_base_url`), compared by
`tests/content/test_render_golden.py`. After an intended change to the HTML or
text, rewrite them and review the diff in the commit:

```bash
NEWSLETTER_UPDATE_GOLDEN=1 uv run --directory modules/newsletter pytest \
  tests/content/test_render_golden.py -q -p no:cacheprovider
```

Structural assertions sit alongside: no `<script`, no `style=` from input, every
`<img src>` and `<a href>` absolute, and the footer present.
