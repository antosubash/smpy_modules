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
Public availability shows `seats_left` only for double opt-in forms whose event shows seats; a single
opt-in form shows `few_left` (a fifth of the capacity or less), never a number.

## Bounds on the anonymous route (defaults)

Per IP 5 per 10 minutes; per address 3 mails per day per form (`public_submissions_confirm_rate_per_email`);
the captcha when configured. There is no per-type budget for registrations. Mails (confirmation,
"already registered", "full/closed") go to whatever address was typed: records has no suppression list
for its own mails, as for its other public confirmations.

## Links

Mail links come from configuration only: the confirm and cancel links from `public_base_url`, the
event page and `.ics` from the tenant's configured public origin; never from a request header. With no
trusted origin the mail has no event link. The `.ics` is linked, not attached (the framework mailer
has no attachments).
