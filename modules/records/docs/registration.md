# Event registration (the `registration` kind)

A registration type is a records type of kind `registration`. Records owns the people (the record is
the registration); the events module owns the seats. A form is attached to an event in the event
editor; the event and the occurrence come only from the signed, event-bound token the availability
route issues (`GET /api/records/submissions/{type}/registration`).

## When a seat is taken

- **Double opt-in (default):** at the confirmation. A submit creates a pending record and mails the
  confirmation; it takes no seat and changes no public number. The confirm link's page takes the seat
  and marks the record registered in one transaction; if the event filled up meanwhile it says so and
  the record stays pending until the retention sweep removes it (no waitlist).
- **Single opt-in:** at submit. Anyone can take seats without confirming an address; the bounds are the
  per-IP limit, the per-address mail bound and the captcha. The event editor warns about this.

An unconfirmed record is kept for `pending_hold_hours` (default 1, at most 168), then purged.

## One answer

The submit route answers the same 202 for a new, a pending, a confirmed and a cancelled address; what
happened is told by mail to that address only. A public event that is full, closed or cancelled
refuses everyone alike; one that is not public (or not this form's) answers like an invalid token.
What the public availability may show is decided by the events module (the contract returns only
what may be published, never raw counts): with the event's "show seats" off, the states are `open`,
`not_open_yet`, `closed`, `full` and `cancelled` only (`unavailable` is the shared 404), no number
and no `few_left`. With it on, a double opt-in form shows
the exact `seats_left`; a single opt-in form shows `few_left` (a fifth of the capacity or fewer),
never a number.

**Residual, stated plainly.** On a single opt-in form the seat is taken at submit, so a submit by a new
address can flip a public state (open to few-left when seats are shown, and to `full` always), and an
observer can see that. A double opt-in form does not have this, because its seat is taken at
confirmation. Use double opt-in for capacity-limited events (the event editor warns about it).

## Bounds on the anonymous route (defaults)

Three limits, then the captcha when one is configured. They are records' existing public-submission
settings, shared with every other form:

- **per IP:** `public_submissions_rate_per_ip`, 5 per 10 minutes (an IPv6 client is counted by its /64, for every submission form);
- **per form and event, in total:** `public_submissions_type_rate`, 60 per hour for everyone together, counted separately for each event the form serves (the event the verified token names, never the body), so a flood on one event does not block the form's other events. Every
  accepted submit creates a pending record and mails an address the caller typed, so this is what
  bounds a distributed sender (it keeps the route from creating unbounded pending records or mailing
  unbounded distinct third-party addresses from the site's domain). Over it the route answers the
  same 429 with `Retry-After` as every other form, identical for every address;
- **per address:** `public_submissions_confirm_rate_per_email`, 3 mails a day per form.

A token that fails verification names no event: all of them share one per-tenant bucket (the attempts rate), so forged tokens cannot mint buckets or spend a real form's budget.

Order on a registration submit with a captcha configured: per IP; a separate **attempts** bucket per event (ten times the form total, e.g. 600/hour for the default 60/hour), charged before the captcha provider is called, so a flood of wrong answers can neither call the provider nor run the pattern worker without bound; then the captcha; then the strict form total, charged right after the captcha passes and before the pattern check. A submit that fails the captcha consumes attempts, never the total, so a real registrant with a right answer still gets in. With no captcha configured nothing proves a human, so the strict total is charged first, as for any other form: recommend a captcha for capacity-limited public registration. Confirming and cancelling are not submits and are never counted. An attacker can exhaust the form
total for one window and lock new submits out until it passes; nobody loses a seat they held (a seat
is taken at confirmation). For a large event's opening minute an operator should raise
`public_submissions_type_rate` (for example `600/hour`) on the Settings screen beforehand, and may add
the captcha. Mails (confirmation, "already registered", "full/closed") go to whatever address was
typed: records has no suppression list for its own mails, as for its other public confirmations.

## Links

Mail links come from configuration only: the confirm and cancel links from `public_base_url`, the
event page and `.ics` from the tenant's configured public origin; never from a request header. With no
trusted origin the mail has no event link. The `.ics` is linked, not attached (the framework mailer
has no attachments).

## What a repeated submit does

A submit for an address that already holds a live registration for that occurrence answers the same
neutral 202 as a new address. Behind it, a pending registration is mailed its confirmation again and
a registered one an "already registered" mail that carries a cancel link, both within the address's
own budget (3 mails a day per form; past it nothing is sent and the answer is unchanged). The mail
goes only to that address, so the form is no oracle for who is registered.

## Limits of what the public surface hides

- **Timing.** A submit for a new address writes a record (an insert, its index rows and a revision);
  one for an address that already holds a live registration for that occurrence writes none. The
  answer and the mail routing are identical, but the latency gap can tell an observer, with many
  careful measurements, whether an address already registered. It is not removed (doing the same
  writes on both paths would mean storing a record we then discard); the per-address mail bound and
  the per-IP limits keep the number of measurements small.
- **A calendar made private or trashed while an admit is in flight.** Admit locks the event row, not
  the calendar's, so at most one admit already in flight can land after the change. The registration
  then belongs to an event that is no longer public. It is kept like any other (it is released when
  the registration is cancelled, trashed or purged); the reconcile job frees only seats that have no
  live registration, so it does **not** remove this one.

- **Busy seats.** A repeated submit never calls the seat contract (a pending record takes its seat
  only at its confirmation, a registered one already holds it), so it always answers the uniform 202.
  A submit that would create a *new* record on a single opt-in form can answer `409 seats_busy` when
  events could not settle its locks (rare, and a "try again"); an address that already holds a live
  registration answers 202 at that moment. That is the one difference by address, it needs events to
  be failing under contention, and it is pinned by `test_uniform_answer.py`. A full event answers
  `registration_full` for everyone alike, before anything about the address is read.
- **The event's internal id is in the registration token and the panel.** The token (and the panel's
  route and props) carry the event's internal id and occurrence key: signed, so they cannot be
  forged or pointed at another event, but not secret. This leaks nothing today: an event that is
  hidden, a draft, private or unknown answers the same 404 as any other, and the id alone gives no
  access (every read re-checks the public gate). Public surfaces naming events by slug instead is a
  tracked follow-up.

