"""External ICS subscriptions (PR 10): a calendar overlays a remote feed, read-only.

The rules, in brief (the plan's Rulings 1-35 are the full text):

- The address is a credential and is **sealed** at rest (``urls``); only ``scheme://host/…`` is
  ever shown, logged or returned.
- It is fetched by a server on the user's behalf, so every address passes the same guard on save
  **and** on every fetch and every redirect hop (``url_safety``, ``policy``), the connection is
  pinned to the address that was checked (``client``), and what comes back is bounded in time,
  bytes and parser work (``fetch``).
- A failure is one of a closed set of codes; no remote text, address or timing reaches a user.
- External events are never re-exported in this module's feeds, never reminded and never offered
  as newsletter cards.
"""
