"""One recipient's message, personalised from the campaign's render snapshot.

The worker never renders (ruling S1): it fills the snapshot's merge tags with
the row's first name and the send's own unsubscribe link. Tokens are minted
here and never stored, one per purpose (ruling T17: ``u``, ``o``, ``c``). The
unsubscribe URL lands in the HTML, the text and, when the transport can carry
it, ``List-Unsubscribe``.
"""

from __future__ import annotations

from collections.abc import Mapping

from sm_newsletter.content.render import RenderedTemplate, personalise
from sm_newsletter.core import tokens
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.models import CampaignRender, Send
from sm_newsletter.sending.transport import OutgoingMessage, unsubscribe_headers
from sm_newsletter.tracking.rewrite import TRACKING_OFF, Tracking, fill

__all__ = ["compose"]


def compose(
    render: CampaignRender,
    send: Send,
    *,
    secret: str,
    list_unsubscribe: bool,
    tracking: Tracking = TRACKING_OFF,
    links: Mapping[int, str] | None = None,
) -> OutgoingMessage:
    """``send``'s message. ``ValueError`` (naming the field, never the value)
    when a personalised header would carry a line break or control character;
    a first name is flattened to one line first, so it never causes one. ``fill``
    raises the same ``ValueError`` for a tracking placeholder with no stored link
    when click tracking is off (with clicks on, the placeholder becomes the click
    URL and no stored link is read). Each purpose gets its own token (T17).
    ``fill`` runs on the trusted snapshot before ``personalise`` (B2), so
    recipient data never reaches it."""
    assert send.id is not None

    def token(purpose: tokens.Purpose) -> str:
        assert send.id is not None
        return tokens.sign(
            secret,
            purpose=purpose,
            tenant_id=send.tenant_id,
            campaign_id=send.campaign_id,
            send_id=send.id,
        )

    url = tokens.unsubscribe_url(render.public_base, token("u"))
    html = fill(
        render.html,
        open_token=token("o") if tracking.opens else "",
        click_token=token("c") if tracking.clicks else "",
        public_base=render.public_base,
        links=links or {},
        tracking=tracking,
    )
    template = RenderedTemplate(subject=render.subject, html=html, text=render.text, warnings=())
    email = personalise(template, first_name=send.first_name, unsubscribe_url=url)
    return OutgoingMessage(
        ref=f"campaign={send.campaign_id} send={send.id}",
        sender=check_header_text(render.sender, field="sender"),
        to=check_header_text(send.email, field="to"),
        subject=email.subject,
        html=email.html,
        text=email.text,
        reply_to=check_header_text(render.reply_to, field="reply_to") if render.reply_to else None,
        headers=unsubscribe_headers(url) if list_unsubscribe else {},
    )
