"""The share picker's response."""

from __future__ import annotations

from pydantic import BaseModel


class ShareCandidate(BaseModel):
    id: str
    display_name: str
    email: str
