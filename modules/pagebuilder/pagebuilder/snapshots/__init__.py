"""Whole-site content snapshots: capture, restore, and the gate between them.

The module's page-level history (``PageRevision``, ``diff``, the approval
workflow) answers *what changed on this page*. This package answers the other
question — *what does the site look like right now, and how do I put it back* —
by serialising every page, redirect, the layout and the media library into a
portable bundle.

Nothing here interprets content. It rewrites asset URLs, translates host-local
foreign keys to slugs, and otherwise moves documents around verbatim.
"""

from __future__ import annotations
