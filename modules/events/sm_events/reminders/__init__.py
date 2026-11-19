"""Reminders: a signed-in user follows an event and is mailed before it starts.

The contract, in three sentences. A reminder goes out **at most once** per occurrence, start,
recipient and lead time: the claim row in ``events_reminder_sent`` is committed before any
mail is handed to the transport, a failed or unfinished row is final, and nothing ever retries.
Whether someone may still be reminded is decided from current state at send time (their
account, their membership, their access to the event), never from anything stored with the
follow. A follow is one user's private data: it is tenant-bound, user-bound, and no route shows
anyone else's.
"""
