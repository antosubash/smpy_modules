"""Request and response bodies of the test-send API.

Addresses are stripped, lowercased and deduped (first one wins the order)
*before* the 1-to-5 count, so ``[" A@x.org", "a@X.org"]`` is one recipient.
An address holding a line break or another control character is refused
before the address parser sees it; the route validates through
``parse_payload``, whose 422 never echoes the input.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from sm_newsletter.campaigns.test_send import MAX_TEST_RECIPIENTS
from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.core.headers import check_header_text

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


Address = Annotated[EmailStr, Field(max_length=MAX_EMAIL_LEN)]


class TestSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipients: Annotated[
        list[Address],
        Field(min_length=1, max_length=MAX_TEST_RECIPIENTS),
        BeforeValidator(_normalise),
    ]


class TestSendResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient: str
    outcome: str
    code: int | None
    detail: str


class TestSendOut(BaseModel):
    results: list[TestSendResultOut]
