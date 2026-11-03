"""Request and response bodies of the settings API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SmtpPasswordUpdate(BaseModel):
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("password")
    @classmethod
    def _stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("password must not be blank")
        return value


class SmtpPasswordOut(BaseModel):
    """Whether a password is stored; the value itself is never returned."""

    has_password: bool
