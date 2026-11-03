"""Snapshot plan bundle builder."""

import json


def _bundle(tmp_path, pages, redirects=None, layout=None):
    root = tmp_path / "bundle"
    (root / "pages").mkdir(parents=True, exist_ok=True)
    for payload in pages:
        full = {
            "slug": payload["slug"],
            "title": payload.get("title", payload["slug"].title()),
            "status": payload.get("status", "draft"),
            "parent_slug": None,
            "draft_data": payload.get("draft_data", {}),
            "published_data": None,
            **{k: v for k, v in payload.items() if k not in ("slug", "draft_data")},
        }
        (root / "pages" / f"{payload['slug']}.json").write_text(json.dumps(full))
    (root / "redirects.json").write_text(json.dumps(redirects or []))
    (root / "layout.json").write_text(json.dumps(layout or {}))
    return root
