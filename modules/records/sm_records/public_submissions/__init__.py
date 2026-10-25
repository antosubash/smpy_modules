"""Record types that accept submissions from the website (#101).

A type opts in with a ``public_submissions`` config (one nullable JSON column
on ``records_type``) whose ``kind`` is ``"form"`` (a contact form) or
``"subscription"`` (a newsletter list). With no config a type behaves exactly
as it always has.

- :mod:`.spec` — the canonical ``sm_*`` system fields of each kind, and their
  injection into every saved schema.
- :mod:`.config` — the rules the config obeys on save.
- :mod:`.definition`, :mod:`.submit` — the anonymous form and its pipeline;
  :mod:`.abuse` and :mod:`.tokens` the checks before the write.
- :mod:`.mail`, :mod:`.mail_runner` — the notification, through the outbox or
  after the commit; :mod:`.system` writes its delivery mark.
- :mod:`.actions` — resend, spam and not spam; on a list, resend the
  confirmation and unsubscribe.
- :mod:`.subscribe` — a newsletter signup's state machine; :mod:`.confirmation`
  its mail, :mod:`.links` the signed confirm and unsubscribe links, and
  :mod:`.opt_in` what following them does.

The routes are ``endpoints/api/public_submissions_public.py`` and ``…_links.py``
(anonymous), ``…_admin.py``, and the landing pages
``endpoints/public_submissions_views.py``.

The contract is :mod:`sm_records.contracts.public_submissions`.
"""
