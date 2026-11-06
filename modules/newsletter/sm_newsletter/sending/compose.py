"""One recipient's message, personalised from the campaign's render snapshot.

The worker never renders (ruling S1): it fills the snapshot's merge tags with
the row's first name and the send's own unsubscribe link (ruling S10: one
token per send, minted here and never stored). The same URL lands in the
HTML, the text and, when the transport can carry it, ``List-Unsubscribe``.
"""

from __future__ import annotations

from sm_newsletter.content.render import RenderedTemplate, personalise
from sm_newsletter.core import tokens
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.models import CampaignRender, Send
from sm_newsletter.sending.transport import OutgoingMessage, unsubscribe_headers

__all__ = ["compose"]


def compose(
    render: CampaignRender, send: Send, *, secret: str, list_unsubscribe: bool
) -> OutgoingMessage:
    """``send``'s message. ``ValueError`` (naming the field, never the value)
    when a personalised header would carry a line break or control character;
    a first name is flattened to one line first, so it never causes one."""
    assert send.id is not None
    token = tokens.sign(
        secret, tenant_id=send.tenant_id, campaign_id=send.campaign_id, send_id=send.id
    )
    url = tokens.unsubscribe_url(render.public_base, token)
    template = RenderedTemplate(
        subject=render.subject, html=render.html, text=render.text, warnings=()
    )
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
