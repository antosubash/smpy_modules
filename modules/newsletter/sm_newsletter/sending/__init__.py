"""Getting campaigns out of the server.

* ``transport`` - the mail transports (SMTP, console);
* ``lock``, ``budget``, ``ledger`` - the install-wide dispatch lock, the rolling
  send budget and the attempt ledger it counts;
* ``freeze``, ``freeze_fence`` - a due campaign's audience frozen into send rows,
  under a one-owner claim per campaign and generation;
* ``compose``, ``classify``, ``rows`` - one recipient's message from the render
  snapshot, the relay's answer as a verdict, and the row and counters it moves;
* ``deliver`` - one recipient through the ledger;
* ``upkeep`` - the dispatcher's bookkeeping (expired leases, finishing, pausing);
* ``dispatch`` - the dispatcher tick;
* ``runtime`` - the tick in a Celery worker (``newsletter.dispatch``): settings,
  secret key and transport read without an app, or the tick refused.
"""
