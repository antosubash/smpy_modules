"""Getting campaigns out of the server.

* ``transport`` - the mail transports (SMTP, console);
* ``freeze`` - a due campaign's audience frozen into send rows;
* ``deliver`` - one recipient through the ledger;
* ``dispatch`` - the dispatcher tick;
* ``runtime`` - the tick in a Celery worker (``newsletter.dispatch``): settings,
  secret key and transport read without an app, or the tick refused.
"""
