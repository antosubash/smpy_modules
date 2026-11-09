"""Link placeholders and the open pixel (T1, T3).

``prepare`` runs once on the snapshot: each trackable ``<a href>`` becomes
``{{link:N}}`` and ``{{open_pixel}}`` is added before ``</body>``. ``fill`` runs per
recipient on that trusted snapshot, before merge fields (B2), so recipient data
can never introduce a placeholder.
"""

from __future__ import annotations

import html as _html
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

from sm_newsletter.content.urls import LINK_PREFIX, MAX_URL, PIXEL_TAG, is_http_link
from sm_newsletter.core import tokens
from sm_newsletter.core.constants import MAX_LINK_URL, MAX_TRACKED_LINKS, PUBLIC_PREFIX

__all__ = ["PIXEL_HTML", "PIXEL_TAG", "TRACKING_OFF", "Prepared", "Tracking", "fill", "prepare"]

log = logging.getLogger(__name__)

PIXEL_HTML = (
    '<img src="{src}" width="1" height="1" alt="" border="0" '
    'style="display:block;width:1px;height:1px;border:0;margin:0;padding:0">'
)
_HREF = re.compile(r'<a href="([^"]*)"')
_PLACEHOLDER = re.compile(r'href="\{\{link:(\d{1,4})\}\}"')


@dataclass(frozen=True)
class Tracking:
    opens: bool
    clicks: bool


TRACKING_OFF = Tracking(opens=False, clicks=False)


@dataclass(frozen=True)
class Prepared:
    html: str
    links: tuple[str, ...]  # links[i] is position i + 1, unescaped


def prepare(html: str, *, own_base: str, campaign_id: int) -> Prepared:
    """``campaign_id`` only names the campaign in the one WARNING per call."""
    if LINK_PREFIX in html or PIXEL_TAG in html:
        raise ValueError("the body already holds a tracking placeholder")
    own = own_base.rstrip("/") + PUBLIC_PREFIX if own_base else ""
    positions: dict[str, int] = {}
    capped = False

    def repl(m: re.Match[str]) -> str:
        nonlocal capped
        value = _html.unescape(m.group(1))
        if value.lower().startswith(("http://", "https://")) and len(value) > min(
            MAX_URL, MAX_LINK_URL
        ):
            capped = True  # too long to store: untracked
            return m.group(0)
        if not is_http_link(value):
            return m.group(0)
        if own and value.startswith(own):
            return m.group(0)
        if value not in positions:
            if len(positions) >= MAX_TRACKED_LINKS:
                capped = True
                return m.group(0)
            positions[value] = len(positions) + 1
        return f'<a href="{LINK_PREFIX}{positions[value]}}}}}"'

    out = _HREF.sub(repl, html)
    if capped:
        log.warning(
            "newsletter: campaign %s has links beyond the tracking limits; they are untracked",
            campaign_id,
        )
    end = out.rfind("</body>")
    out = out + PIXEL_TAG if end < 0 else out[:end] + PIXEL_TAG + out[end:]
    return Prepared(out, tuple(positions))


def fill(
    html: str,
    *,
    open_token: str,
    click_token: str,
    public_base: str,
    links: Mapping[int, str],
    tracking: Tracking,
) -> str:
    def link(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if tracking.clicks:
            target = tokens.click_url(public_base, click_token, n)
        elif n in links:
            target = links[n]
        else:
            raise ValueError("a link placeholder has no stored link")
        return f'href="{_html.escape(target, quote=True)}"'

    out = _PLACEHOLDER.sub(link, html)
    pixel = ""
    if tracking.opens:
        src = _html.escape(tokens.open_url(public_base, open_token), quote=True)
        pixel = PIXEL_HTML.format(src=src)
    return out.replace(PIXEL_TAG, pixel)
