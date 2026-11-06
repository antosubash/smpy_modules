"""The only package that knows news and pagebuilder *might* be installed (ruling R2).

Both are optional extras, so every import of theirs is deferred and guarded, and
reads go only through their ``contracts``. A source is available when its
contract imports *and* its module is mounted on this app
(``app.state.news`` / ``app.state.pagebuilder``); otherwise its routes answer
409 ``integration_unavailable`` and the editor hides its card from the palette.
"""

from __future__ import annotations

from typing import Any

from sm_newsletter.content.integrations import news, pagebuilder
from sm_newsletter.content.integrations.hits import CardHit, MediaHit, like_pattern

__all__ = ["CardHit", "MediaHit", "capabilities", "like_pattern"]


def capabilities(app: Any) -> dict[str, bool]:
    """Which card sources this app offers; the editor's ``capabilities`` prop."""
    return {"news": news.available(app), "pagebuilder": pagebuilder.available(app)}
