"""What the settings and test-send bodies share for a list of addresses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from pydantic import EmailStr, Field

from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.core.headers import check_header_text

Address = Annotated[EmailStr, Field(max_length=MAX_EMAIL_LEN)]


def normaliser(field: str) -> Callable[[Any], Any]:
    """A before-validator: each string stripped, header-checked (named ``field``
    in the error), lower-cased, and the list deduplicated (first wins)."""

    def normalise(value: Any) -> Any:
        if not isinstance(value, list):
            return value  # the list validator refuses it
        out: list[Any] = []
        for item in value:
            if isinstance(item, str):
                item = check_header_text(item.strip(), field=field).lower()
            if item not in out:
                out.append(item)
        return out

    return normalise
