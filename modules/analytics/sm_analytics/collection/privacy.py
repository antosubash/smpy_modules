"""Reduce request metadata before anything reaches storage."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from urllib.parse import unquote, urlsplit

from sm_analytics.core.constants import EXCLUDED_SEGMENTS


def canonical_path(path: str, patterns: list[str], kind: str) -> str | None:
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return None
    clean = urlsplit(path).path
    decoded = unquote(clean).lower()
    if any(s in EXCLUDED_SEGMENTS or s in {".", ".."} for s in decoded.split("/")):
        return None
    if any(ord(c) < 32 for c in decoded) or "\\" in decoded or len(clean) > 500:
        return None
    for pattern in patterns:
        regex = "/".join("[^/]+" if s.startswith(":") else re.escape(s) for s in pattern.split("/"))
        if re.fullmatch(regex, clean):
            return pattern if kind == "application" else clean
    return None


def visitor_key(
    secret: str, tenant: str, property_id: str, ip: str, browser: str, now: datetime
) -> str:
    if not secret:
        raise ValueError("Analytics requires a provisioned host secret")
    message = json.dumps([tenant, property_id, now.date().isoformat(), ip, browser])
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def user_agent(value: str) -> tuple[str, str, str]:
    value = value.lower()
    browser = next(
        (
            name
            for token, name in [
                ("edg/", "Edge"),
                ("firefox/", "Firefox"),
                ("chrome/", "Chrome"),
                ("safari/", "Safari"),
            ]
            if token in value
        ),
        "Other",
    )
    os = next(
        (
            name
            for token, name in [
                ("android", "Android"),
                ("iphone", "iOS"),
                ("ipad", "iOS"),
                ("windows", "Windows"),
                ("mac os", "macOS"),
                ("linux", "Linux"),
            ]
            if token in value
        ),
        "Other",
    )
    device = (
        "tablet"
        if "ipad" in value or "tablet" in value
        else "mobile"
        if "mobile" in value
        else "desktop"
    )
    return browser, os, device


def referrer_host(value: str) -> str:
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
        return (parts.hostname or "")[:253] if parts.scheme in {"http", "https"} else ""
    except ValueError:
        return ""
