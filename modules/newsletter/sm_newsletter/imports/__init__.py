"""Mailchimp import (PR 7).

Rulings this package keeps (plan R2, R3, R6, R14):

* R2: the upload is parsed into staged rows (``newsletter_import_row``) in one
  request; nothing reaches records until the operator confirms a mapping.
* R3: one staged row per address. When an address appears in several files the
  kind with the lowest ``KIND_ORDER`` wins (cleaned over unsubscribed over
  subscribed), so an opt-out in any export is never lost to a "subscribed" one.
* R6: staged rows hold the cleaned address and its non-empty cells only; no
  error, log or API response repeats a cell value.
* R14: ``outcome`` is ``NULL`` while a row is still to do; the applier works the
  rows in ``seq`` order, resumably, under the job's lease.

An import never emits pending -> confirmed, never clears a suppression and never
resubscribes an opted-out person.
"""
