"""Seal Stripe secrets on supported settings writes, without changing held values."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, PlainSerializer

from sm_billing.core import crypto


def seal_secret(value: str | None) -> str:
    """Dump plaintext encrypted; preserve empty values and any ``enc:`` prefix.

    A process with no live app may dump legacy values during hydration. Every
    supported writer registers an app first; a live app without a secret key
    raises rather than persisting plaintext. Serialization never mutates the
    value held by settings or changes the framework's reload comparisons.
    """
    text = (value or "").strip()
    if not text or crypto.is_encrypted(text) or not crypto.has_secret_provider():
        return text
    return crypto.encrypt_value(text)


SealedSecret = Annotated[
    str | None,
    AfterValidator(lambda value: value or ""),
    PlainSerializer(seal_secret, return_type=str),
]
"""Nullable string selects the framework's JSON validated-dump storage path.

Legacy ``string`` rows still hydrate. A nullable clear reads as ``""``; a new
nonempty plaintext write stores ``enc:v2:`` under the running app's secret.
"""
