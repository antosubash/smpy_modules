"""The email renderer: blocks to a table-based HTML part and a plain-text part.

:func:`render` runs once per campaign and leaves the merge tags in place;
:func:`personalise` fills them per recipient.
"""

from __future__ import annotations

import unicodedata

from sm_newsletter.content.merge import personalise_html, personalise_text
from sm_newsletter.content.render import footer, styles
from sm_newsletter.content.render import html as h
from sm_newsletter.content.render import text as tx
from sm_newsletter.content.render.types import (
    Branding,
    FooterCopy,
    RenderContext,
    RenderedEmail,
    RenderedTemplate,
    RenderInput,
)
from sm_newsletter.core.headers import check_header_text

__all__ = [
    "Branding",
    "FooterCopy",
    "RenderContext",
    "RenderInput",
    "RenderedEmail",
    "RenderedTemplate",
    "personalise",
    "render",
]

WARN_RELATIVE = "relative_urls"
WARN_NO_ADDRESS = "physical_address_missing"
WARN_EMPTY = "empty_body"


def render(inp: RenderInput, ctx: RenderContext) -> RenderedTemplate:
    """Raises ``ValueError`` for an accent that is not a hex colour."""
    styles.link_style(ctx.branding.accent)  # the accent lands in attributes: refuse a bad one
    rows = [h.header(ctx), *(h.block(b, ctx) for b in inp.blocks), footer.html(ctx)]
    page = h.shell(subject=inp.subject, preheader=inp.preheader, locale=ctx.locale, rows=rows)
    paragraphs = [p for p in (tx.block(b, ctx) for b in inp.blocks) if p]
    text = "\n\n".join([*paragraphs, footer.text(ctx)]) + "\n"
    warnings: list[str] = []
    if not ctx.content_base or not ctx.public_base:
        warnings.append(WARN_RELATIVE)
    if not ctx.physical_address.strip():
        warnings.append(WARN_NO_ADDRESS)
    if not inp.blocks:
        warnings.append(WARN_EMPTY)
    return RenderedTemplate(subject=inp.subject, html=page, text=text, warnings=tuple(warnings))


def _one_line(value: str | None) -> str | None:
    """A name fit for a header: control and line-separator characters become spaces."""
    if value is None:
        return None
    bad = ("Cc", "Zl", "Zp")
    cleaned = "".join(" " if unicodedata.category(ch) in bad else ch for ch in value)
    return " ".join(cleaned.split())


def personalise(
    t: RenderedTemplate, *, first_name: str | None, unsubscribe_url: str
) -> RenderedEmail:
    name = _one_line(first_name)
    subject = personalise_text(t.subject, first_name=name, unsubscribe_url=unsubscribe_url)
    return RenderedEmail(
        subject=check_header_text(subject, field="subject"),
        html=personalise_html(t.html, first_name=name, unsubscribe_url=unsubscribe_url),
        text=personalise_text(t.text, first_name=name, unsubscribe_url=unsubscribe_url),
    )
