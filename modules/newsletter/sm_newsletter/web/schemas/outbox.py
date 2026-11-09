"""The console outbox as JSON."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OutboxMessage(BaseModel):
    to: str
    subject: str
    html: str
    text: str
    headers: dict[str, str]
    at: datetime
