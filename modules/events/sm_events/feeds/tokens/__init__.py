"""Private feed links: one token per user and calendar, serving what that user may see now.

The rules, in brief (the plan's Rulings 1 to 16):

* A token is ``evf_`` plus 32 random bytes, base64url. Only its SHA-256 is stored, so a leaked
  database cannot be replayed and nothing depends on ``SM_SECRET_KEY``. It is shown once, in the
  create response, and appears in no list, log line or error.
* The feed route finds the row by hash in one narrow cross-tenant read, binds **that row's**
  tenant (the module's third documented exception, after newsletter's unsubscribe link and
  records' form token), and re-derives the owner's access on every request through the offline
  principal. Nothing is cached, so a revoked share, a deactivated account or a trashed calendar
  stops the feed on the next fetch.
* Every refusal is one response (:func:`sm_events.web.endpoints.public._private_feed.deny`),
  held back to a latency floor, so a token cannot be probed.
"""
