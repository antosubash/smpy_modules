"""The unsubscribe page's markup (S9): one plain form, no script, no external asset.

It is opened from a mail client, often in its built-in browser, so it is a
self-contained server-rendered document, not an Inertia page. Nothing in it
depends on the token: every link renders the same bytes.
"""

from __future__ import annotations

from html import escape

__all__ = ["KEYS", "render_page"]

KEYS = ("title", "intro", "button", "done")

_STYLE = (
    "body{margin:0;background:#f4f4f5;color:#18181b;"
    "font:16px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
    "main{max-width:28rem;margin:4rem auto;padding:2rem;background:#fff;border-radius:.5rem}"
    "h1{font-size:1.25rem;margin:0 0 1rem}"
    "button{font:inherit;padding:.5rem 1rem;border:0;border-radius:.375rem;"
    "background:#18181b;color:#fff;cursor:pointer}"
)


def render_page(*, copy: dict[str, str], locale: str, done: bool) -> str:
    """The form (``done=False``) or the answer to any POST (``done=True``)."""
    e = {key: escape(value, quote=True) for key, value in copy.items()}
    if done:
        body = f"<p>{e['done']}</p>"
    else:
        body = (
            f"<p>{e['intro']}</p>"
            f'<form method="post"><button type="submit">{e["button"]}</button></form>'
        )
    return (
        "<!doctype html>"
        f'<html lang="{escape(locale, quote=True)}">'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{e['title']}</title><style>{_STYLE}</style></head>"
        f"<body><main><h1>{e['title']}</h1>{body}</main></body></html>"
    )
