"""What ``app.state.sm_newsletter`` holds."""

from __future__ import annotations

from dataclasses import dataclass

from sm_newsletter.core.settings import NewsletterSettings


@dataclass
class NewsletterServices:
    settings: NewsletterSettings
