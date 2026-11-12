"""Request and response bodies of the test-send API.

Addresses are stripped, lowercased and deduped (first one wins the order)
*before* the 1-to-5 count, so ``[" A@x.org", "a@X.org"]`` is one recipient.
An address holding a line break or another control character is refused
before the address parser sees it; the route validates through
``parse_payload``, whose 422 never echoes the input.

The address parser then folds the domain (a fullwidth letter, punycode), so
the list is deduplicated again after it on the canonical form
(``normalise_email``: the domain as the parser has it, the local part NFC and
lower-cased), so two spellings of one mailbox are one recipient (#348).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from sm_newsletter.campaigns.test_send import MAX_TEST_RECIPIENTS
from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.core.suppression.hashing import normalise_email

__test__ = False  # a module named test_*, not a pytest test module


def _normalise(value: Any) -> Any:
    if not isinstance(value, list):
        return value  # the list validator refuses it
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            item = check_header_text(item.strip(), field="recipients").lower()
        if item not in out:
            out.append(item)
    return out


def _dedup(value: list[str]) -> list[str]:
    """First spelling of each mailbox wins."""
    seen: dict[str, str] = {}
    for item in value:
        seen.setdefault(normalise_email(item), item)
    return list(seen.values())


Address = Annotated[EmailStr, Field(max_length=MAX_EMAIL_LEN)]

class TestSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipients: Annotated[
        list[Address],
        Field(min_length=1, max_length=MAX_TEST_RECIPIENTS),
        BeforeValidator(_normalise),
        AfterValidator(_dedup),
    ]


class TestSendResultOut(BaseModel):
    """One recipient's answer: the outcome (``accepted``, ``rejected``,
    ``unknown``, ``failed``, ``recipient_not_allowed``, ``suppressed``) and a
    stable code (``smtp_<reply>``, ``dispatch_busy`` or ``None``). The relay's
    reply text is never returned (#348); it is in the ledger and the log."""

    model_config = ConfigDict(from_attributes=True)

    recipient: str
    outcome: str
    code: str | None


class TestSendOut(BaseModel):
    results: list[TestSendResultOut]
