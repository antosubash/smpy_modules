"""Request and response bodies of the preview API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from sm_newsletter.web.schemas.campaigns import Preheader, Subject


class PreviewIn(BaseModel):
    """Unsaved editor content. ``body`` is validated with ``parse_body``
    (422 ``invalid_body``); the headers follow the campaign rules."""

    model_config = ConfigDict(extra="forbid")

    subject: Subject = ""
    preheader: Preheader = ""
    body: list[dict[str, Any]] | Any = []


class PreviewOut(BaseModel):
    subject: str
    html: str
    text: str
    warnings: list[str]
