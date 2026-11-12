"""How an address becomes a suppression key: one canonical form, then SHA-256.

:func:`normalise_email` is the module's one canonical form of an address, used
for every suppression hash and every address comparison (writes from the
``SubscriptionChanged`` handler, the reconcile, imports, lifts, test sends,
freeze and the subscriber browser), so two spellings of one address are one key
whichever side wrote it (#348):

* the whole address is stripped and Unicode-NFKC-normalised (a fullwidth
  letter becomes its ASCII one), then lower-cased with :meth:`str.lower`, as before (not
  ``casefold``, which would turn ``ß`` into ``ss`` and change existing keys);
* the domain's ``xn--`` labels are decoded to Unicode, which is what the
  address parser (``email-validator``, behind ``EmailStr``) does, so
  ``a@xn--bcher-kva.de`` and ``a@bücher.de`` are one key.

A pure-ASCII address without ``xn--`` labels keeps exactly the key it had
(``strip().lower()``). :func:`records_form` is records' own normalisation
(strip and lower-case only): the form to *search records by* or hand records,
whose rows keep the spelling they were written with.
"""

from __future__ import annotations

import hashlib
import unicodedata

__all__ = ["email_hash", "normalise_email", "records_form"]

_ACE_PREFIX = "xn--"


def records_form(address: object) -> str:
    """``address`` stripped and lower-cased (records' normalisation); ``ValueError``
    for an empty or non-string one."""
    if not isinstance(address, str):
        raise ValueError(f"not an email address: {address!r}")
    normalised = address.strip().lower()
    if not normalised:
        raise ValueError("empty email address")
    return normalised


def _label(label: str) -> str:
    if not label.startswith(_ACE_PREFIX):
        return label
    try:
        return label.encode("ascii").decode("idna").lower()
    except UnicodeError:
        return label  # not valid punycode: compared as written


def normalise_email(address: object) -> str:
    """The canonical form of ``address`` (see the module docstring); ``ValueError``
    for an empty or non-string one."""
    folded = unicodedata.normalize("NFKC", records_form(address)).lower()
    local, at, domain = folded.rpartition("@")
    if not at:
        return folded
    return f"{local}@{'.'.join(_label(part) for part in domain.split('.'))}"


def email_hash(address: object) -> str:
    """The hex SHA-256 of the canonical address: what a suppression row stores."""
    return hashlib.sha256(normalise_email(address).encode()).hexdigest()
