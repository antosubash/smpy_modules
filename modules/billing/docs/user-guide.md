# Billing user guide

Two audiences use billing's screens:

- **Platform administrators** (the `admin` role, or `billing.platform.*`
  permissions) work under **Admin → Access → Billing**: Subscriptions, Plans,
  Stripe connection and Usage.
- **Organisation owners** see a **Billing** entry in the app sidebar for the
  organisation they have selected. Organisation admins can view it; only the
  owner can change it.

## Plans (`/admin/billing/plans`)

The table lists every plan with its pricing model, price, seat limit and
badges: **Default** (new organisations get this plan), **Hidden** (not shown to
organisations) and **Archived**. **New plan** opens the editor; **Edit** and
**Archive** act on a row.

### The plan editor

| Field | What it means |
|---|---|
| **Key** | Permanent identifier, e.g. `team`. Lowercase letters, digits, `-` and `_`, up to 64 characters. Cannot be changed after the plan is created. |
| **Name** | What organisations see, up to 120 characters. |
| **Pricing** | **Free**, **Flat price** (one charge per period) or **Per seat** (charged per member; Stripe's quantity follows the member count). |
| **Currency** | Three-letter code (`eur`, `usd`). Must match the Stripe prices. |
| **Stripe price ID (monthly / yearly)** | The `price_…` IDs from your Stripe product. At least one is required for a paid plan; leave yearly blank to sell monthly only. |
| **Monthly / Yearly amount (display)** | What the plan picker shows, e.g. `19` or `19.90`. Display only: Stripe charges whatever the price says. Up to 20,000,000. |
| **Trial days** | Free days before the first charge, 0–730. Each organisation gets one trial in its lifetime. |
| **Sort order** | Position in the plan picker (lower first). |
| **Description** | One or two sentences shown on the plan card. |
| **Limits** | Rows of key and number. `tenants.seats` is the seat limit (members plus pending invitations). **A key you don't add is unlimited; `0` forbids.** Other keys are read by whichever module asks for them. |
| **Limits** for metered features | A module that meters usage (requests, tokens, running jobs) registers a *meter*, and its key appears among the suggestions. The number is the allowance per billing period for a counter (it resets when the period renews) or the most held at once for a gauge (concurrent jobs, reserved storage). Quantities are in the meter's unit: bytes, tokens or milliseconds, not GB or seconds. As for any limit, no row is unlimited and `0` forbids. |
| **Features** | Comma-separated feature keys (`sso, audit-log`). A module asks "does this plan have `sso`?". |
| **Shown to organisations** | Untick to keep a plan off the picker (for plans you assign by hand). |
| **Default plan for new organisations** | Only a free plan can be the default. |

Switching **Pricing** to Free clears the price, amount and trial fields;
switching to a paid model unticks Default. The editor refuses, with a message
in the dialog:

- a paid plan with no Stripe price, or a default plan that isn't free;
- a key or Stripe price another plan already uses;
- changing or removing a Stripe price that an active subscription is billed on
  (`409 price_in_use`) — create a new plan for new pricing instead;
- unsetting Default on the current default — mark another free plan as default
  instead.

When the Stripe provider is active, each price ID is checked against Stripe on
save: it must exist, be active, and match the plan's currency and interval.

**Archive** removes a plan from the picker. Organisations already on it keep
it. The default plan can't be archived.

## Subscriptions (`/admin/billing/subscriptions`)

One row per organisation: its plan (with the interval), subscription status,
member count (and the billed quantity if it differs), and the period end.
**Suspended (unpaid)** marks an organisation billing suspended;
**Suspended** alone means an administrator did. Filter by **Status**.

- With the **manual** provider each row has **Assign plan**: pick a plan and a
  status. Choosing **Unpaid** suspends the organisation; any other status
  lifts a suspension billing made (never one an administrator made on the
  Organisations screen).
- With **Stripe** each row with a Stripe subscription has **Resync**, which
  re-reads it from Stripe — the same as one webhook arriving.
- With **Stripe** a line above the table shows the oldest sync, webhook rows
  not yet processed, and whether the scheduled reconcile is on.

| Status | Shown as | Organisation gets |
|---|---|---|
| `trialing` | Trial | the plan |
| `active` | Active | the plan |
| `past_due` | Payment failed | the plan, plus a payment warning |
| `unpaid` | Unpaid | the default plan; the organisation is suspended |
| `canceled` | Canceled | the default plan |
| `incomplete` | Incomplete | the default plan (the first payment never went through) |
| — | No subscription | the default plan |

## Usage (`/admin/billing/usage`)

One row per organisation and meter, fullest first: **Organisation**,
**Meter** (with **Counter** or **Gauge**), **Used**, **Limit**, **Used %**
with a bar, and the **Period** (a gauge **Never resets**). A meter no module
registers any more is marked **Not registered**. The filters above the table:

- **Meter** — one meter, or **All meters**;
- **Period** — **Current period** or **Previous period** (the period just
  before each organisation's current one; counters only);
- **Organisation** — search by name, slug or ID;
- **Over 80%** — only rows at 80% of their limit or more.

The numbers are the ones enforcement uses: the plan in force and the
organisation's own period (its Stripe period, else the calendar month in
UTC).

**Details** on a row opens a side panel for that organisation:

- **Open holds** — the holds that make up its gauges (a running job, reserved
  storage) with their quantity, status, expiry (**Never (committed)** once
  committed) and source. **Release** returns a hold's capacity; one already
  settled says so. Use it for a slot left behind by a job that died, when
  waiting for the hold to lapse is too long.
- **Ledger** — every change to its counters, newest first: time, kind
  (**Consumed**, **Recorded**, **Refunded**, **Adjusted**), meter, quantity,
  source, and for an adjustment **By** and **Reason**. Filter it with
  **Meter** and **Kind**.
- **Recount {meter}** (one button per gauge) rebuilds the gauge's level from
  its open holds. Use it when the level and the holds disagree.
- **Adjust** opens a dialog: pick a counter, enter a signed **Quantity**
  (negative to credit, positive to charge; a whole number other than 0) and a
  **Reason**, which is required. **Record adjustment** applies it to the
  current period and writes it to the ledger with your reason and your user ID.
  A credit can take the counter below zero, which leaves the organisation
  that much more than its limit for the rest of the period.

Release, Recount and Adjust need `billing.platform.manage`; the table and the
panel need `billing.platform.view`.

## Stripe connection (`/admin/billing/connection`)

- **Webhook endpoint** — the URL to paste into Stripe (copy button).
- **Secret key** and **Webhook signing secret** — stored encrypted. Leave a
  field blank to keep what is stored; tick **Remove the stored value** to clear
  it. Values are never shown again after saving.
- **Return URL origin** — where Stripe sends people back after Checkout and the
  portal, e.g. `https://app.example.com`. Blank uses the address the person is
  on. Must be an `http(s)` origin with no path.

A banner explains when the manual provider is active, or when Stripe is
configured but not usable (a missing secret, or one that can't be decrypted
because the app's secret key changed). Saving new secrets takes effect
immediately; switching between manual and Stripe is a setting on the Settings
screen and also takes effect when saved.

## The organisation's Billing page (`/billing/`)

The card at the top shows the plan in force, its status, seats (**3 members**,
or **2 of 5 seats used** when the plan has a limit), and when it renews or ends.
Below it, the **Usage** card (when anything is metered) shows one row per
metered feature the plan limits or the organisation has used: **3 of 10**
(or **3 used** with **Unlimited** when the plan sets no limit), a bar that
turns amber at 90% (**Almost at the limit**) and red at the limit (**Limit
reached**), and **Resets {date}** for a per-period counter or **In use now**
for a gauge, which never resets. Everyone who can see the Billing page sees
the card. The card is hidden when nothing is metered.

When the organisation reaches a limit, the feature refuses the request and
says so, for example "AI requests limit reached (10/10); resets 1 Nov 2026."
Usage starts again from zero when the period renews; a gauge frees up as
running work finishes. Upgrading to a plan with a higher limit applies at
once; a downgrade below what is already used refuses further use for the
rest of the period and takes nothing back.

Below that, the plan picker lists every visible plan for the chosen billing
period (**Monthly** / **Yearly**). Each card's button says what it will do:

| Button | Happens |
|---|---|
| **Subscribe** | Opens Stripe Checkout. Back on the page, "Activating your subscription…" shows until Stripe confirms; nothing is granted before that. |
| **Switch to this plan** | Asks to confirm, then moves the subscription; Stripe prorates the difference on the next invoice. |
| **Downgrade at period end** | Asks to confirm; the paid plan stays until the period ends, then the organisation is on the free plan. |
| **Current plan** | Nothing to do. |
| **Not available** | That plan isn't sold for this period, or online payment isn't set up. |

A downgrade is refused when the organisation has more members (plus pending
invitations) than the target plan allows — the message says how many to
remove. **Manage payment & invoices** opens the Stripe Customer Portal (card,
invoices, cancellation).

**When a payment fails** the organisation keeps its plan while Stripe retries,
under a **Your last payment failed** banner with an **Update payment method**
button. If the retries run out, the organisation is suspended: members can no
longer use it, but the owner can still open **Billing**, which then shows only
**This organisation is suspended for non-payment** and **Pay now** (the
Customer Portal). Access returns as soon as Stripe confirms the payment. On an
installation without Stripe the same page tells the owner to contact the site
administrator instead.

Only the owner can change the plan or open the portal. Organisation admins see
the page read-only; plain members don't see it.
