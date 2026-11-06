"""What the renderer takes and returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # richtext imports this package; blocks imports richtext
    from sm_newsletter.content.blocks import Block


@dataclass(frozen=True)
class Branding:
    app_name: str
    accent: str  # a hex colour; it lands in style and bgcolor attributes
    logo_url: str  # absolute (or relative without a base); "" = no logo


@dataclass(frozen=True)
class FooterCopy:
    reason: str  # ``{app_name}`` already substituted
    unsubscribe: str
    read_more: str = "Read more"  # the card link's label, in the footer's language


@dataclass(frozen=True)
class RenderContext:
    content_base: str  # the campaign tenant's public origin: links, images, cards
    public_base: str  # the host's ``public_base_url``: newsletter's own routes
    branding: Branding
    physical_address: str
    footer: FooterCopy
    locale: str


@dataclass(frozen=True)
class RenderInput:
    subject: str
    preheader: str
    blocks: list[Block]


@dataclass(frozen=True)
class RenderedTemplate:
    """Merge tags still in place; :func:`~sm_newsletter.content.render.personalise` fills them."""

    subject: str
    html: str
    text: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
