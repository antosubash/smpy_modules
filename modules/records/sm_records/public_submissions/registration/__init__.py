"""Event registration (PR 9): the kind's code, kept apart from the form and the newsletter.

Records owns the *people* (the record is the registration); events owns the *seats*. This package
reaches events only through :mod:`sm_records.integrations.events.registration`, which calls
``sm_events.contracts.registration``, and only lazily, so records installs and runs without it.
"""
