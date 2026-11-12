"""How an address becomes a suppression key: one canonical form, then SHA-256.

:func:`normalise_email` is the module's one canonical form of an address, used
for every suppression hash and every address comparison (writes from the
``SubscriptionChanged`` handler, the reconcile, imports, lifts, test sends,
freeze, the subscriber browser and the test-send allow rule), so two spellings
of one mailbox are one key whichever side wrote it (#348):

* the **local part** is stripped, NFC-normalised and lower-cased with
  :meth:`str.lower`, as before. It is never NFKC-folded: ``ﬀ@x`` and ``ff@x``
  (or a fullwidth letter and its ASCII one) are different mailboxes, and
  ``casefold`` would turn ``ß`` into ``ss`` and change existing keys;
* the **domain** is normalised exactly as the address parser does it
  (``email-validator``'s own ``validate_email_domain_name``: UTS-46 with
  IDNA 2008), so a fullwidth letter, upper case and punycode spell one domain:
  ``xn--fa-hia.de`` is ``faß.de``. A domain it refuses is NFC-normalised and
  lower-cased instead.

A pure-ASCII address keeps exactly the key it had (``strip().lower()``).

Rows a pre-#348 build wrote under a non-ASCII spelling carry the **legacy key**
(``sha256(strip().lower())``), and only the hash is stored, so every lookup that
refuses a send, clears or shows a row also tries it (:func:`lookup_hashes`);
writes use only :func:`email_hash`.

:func:`records_form` is records' own normalisation (strip and lower-case only):
the form to *search records by* or hand records, whose rows keep the spelling
they were written with.
"""

from __future__ import annotations

import hashlib
import unicodedata

from email_validator import EmailSyntaxError
from email_validator.syntax import validate_email_domain_name

__all__ = [
    "email_hash",
    "legacy_hash",
    "lookup_hashes",
    "normalise_email",
    "records_form",
]


def records_form(address: object) -> str:
    """``address`` stripped and lower-cased (records' normalisation); ``ValueError``
    for an empty or non-string one."""
    if not isinstance(address, str):
        raise ValueError(f"not an email address: {address!r}")
    normalised = address.strip().lower()
    if not normalised:
        raise ValueError("empty email address")
    return normalised


def _domain(domain: str) -> str:
    """The domain as ``email-validator`` normalises it (Unicode form)."""
    try:
        result = validate_email_domain_name(
            domain, test_environment=True, globally_deliverable=False
        )
    except (EmailSyntaxError, UnicodeError, ValueError):
        return unicodedata.normalize("NFC", domain).lower()
    return str(result["domain"])


def normalise_email(address: object) -> str:
    """The canonical form of ``address`` (see the module docstring); ``ValueError``
    for an empty or non-string one."""
    stripped = records_form(address)
    local, at, domain = stripped.rpartition("@")
    if not at:
        return unicodedata.normalize("NFC", stripped).lower()
    return f"{unicodedata.normalize('NFC', local).lower()}@{_domain(domain)}"


def email_hash(address: object) -> str:
    """The hex SHA-256 of the canonical address: what a suppression row stores."""
    return hashlib.sha256(normalise_email(address).encode()).hexdigest()


def legacy_hash(address: object) -> str:
    """The key a pre-#348 build wrote: SHA-256 of ``strip().lower()`` only."""
    return hashlib.sha256(records_form(address).encode()).hexdigest()


def lookup_hashes(address: object) -> tuple[str, ...]:
    """Every key a row for ``address`` may be stored under: the canonical one,
    then the legacy one when it differs (a non-ASCII or punycode spelling).

    The legacy key can go once no such row can exist: newsletter's first
    published release, since no published build ever wrote one (CHANGELOG).
    """
    canonical = email_hash(address)
    legacy = legacy_hash(address)
    return (canonical,) if legacy == canonical else (canonical, legacy)
