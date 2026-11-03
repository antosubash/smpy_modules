"""Request and response bodies of the settings API."""

from __future__ import annotations

from pydantic import BaseModel


class SmtpPasswordUpdate(BaseModel):
    """Unconstrained on purpose: a validation error would echo the submitted
    value (``input``) back. The handler validates and never repeats it."""

    password: str


class SmtpPasswordOut(BaseModel):
    """Whether a password is stored; the value itself is never returned."""

    has_password: bool
