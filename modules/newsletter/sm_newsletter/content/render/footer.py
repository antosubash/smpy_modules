"""The fixed footer the editor cannot remove: why you got this, the address, unsubscribe."""

from __future__ import annotations

from sm_newsletter.content.render import html as h
from sm_newsletter.content.render import styles as s
from sm_newsletter.content.render import text as t
from sm_newsletter.content.render.types import RenderContext
from sm_newsletter.content.urls import UNSUBSCRIBE_TAG

_P = "margin:0 0 8px"


def _address_lines(ctx: RenderContext) -> list[str]:
    raw = ctx.physical_address.replace("\r\n", "\n").replace("\r", "\n").strip()
    return [line.strip() for line in raw.split("\n") if line.strip()]


def html(ctx: RenderContext) -> str:
    parts = [f'<p style="{_P}">{h.inert(ctx.footer.reason)}</p>']
    if lines := _address_lines(ctx):
        parts.append(f'<p style="{_P}">{"<br>".join(h.inert(line) for line in lines)}</p>')
    link = f"color:{s.MUTED};text-decoration:underline"
    parts.append(
        f'<p style="margin:0"><a href="{UNSUBSCRIBE_TAG}" style="{link}">'
        f"{h.inert(ctx.footer.unsubscribe)}</a></p>"
    )
    return f'<tr><td style="{s.FOOTER_CELL}">{"".join(parts)}</td></tr>'


def text(ctx: RenderContext) -> str:
    lines = ["--", t.inert(ctx.footer.reason), *(t.inert(x) for x in _address_lines(ctx))]
    lines.append(f"{t.inert(ctx.footer.unsubscribe)}: {UNSUBSCRIBE_TAG}")
    return "\n".join(lines)
