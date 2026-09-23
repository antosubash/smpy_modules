"""Which media library the ``media`` field picker talks to, decided at startup.

``records`` is published on its own and must not depend on another plugin
(:mod:`sm_records.deps` says why), so nothing here imports ``file_storage``.
The picker does not need it to: the browser calls the media library's JSON API
directly, with the session cookie, and that module's own permissions decide
what the caller may list, upload or read. All this module has to know is
*where* that API is, and it learns that from the app itself.

**Detection is by route shape.** The framework ``file_storage`` module mounts
four routes under its ``route_prefix`` (``/api/file-storage`` on a stock
host)::

    POST {prefix}/upload
    GET  {prefix}/files
    GET  {prefix}/files/{file_id}
    GET  {prefix}/files/{file_id}/download

:func:`detect_prefix` looks for a prefix under which all four exist on
``app.routes``. When the host's module registry (``app.state.sm.modules``)
lists a module named ``FileStorage`` its ``meta.route_prefix`` wins among
several matches; with no registry (a test harness) or no such module, exactly
one match is required — two different media APIs is a choice for the
operator, made with ``media_api_prefix``, not a guess made here.

Run from ``on_startup`` because the setting it honours is DB-backed and only
exists as the operator set it from lifespan start on (the same reason
:mod:`sm_records.boot` mounts the public router there). Routes are wired at
build time, so every module's routes are on the app by then.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI, Request

try:
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:  # pragma: no cover - a FastAPI old enough to copy routes up
    _iter_route_contexts = None

from sm_records import constants
from sm_records.settings_checks import check_media_api_prefix

logger = logging.getLogger(__name__)

MEDIA_MODULE_NAME: Final = "FileStorage"
"""``file_storage``'s ``meta.name`` — the one fact about it this module uses."""

ID_PLACEHOLDER: Final = "{id}"
"""What the browser replaces with a file id in the two URL templates."""

_DOWNLOAD_RE: Final = re.compile(r"^(?P<prefix>/.+)/files/\{[^/{}]+\}/download$")
_FILE_RE: Final = re.compile(r"^/files/\{[^/{}]+\}$")
_SEARCH_PARAMS: Final = ("q", "search")
"""Query parameters the list route may declare for a filename search. The
stock ``file_storage`` list declares neither (``page``/``per_page`` only), so
the picker filters the loaded page instead and says so; a media API that does
declare one is searched server-side without a change here."""

_PROBE_ID: Final = str(uuid.UUID(int=0))
"""A syntactically valid file id, for asking the public-route registry whether
a download URL would be served to an anonymous caller."""


@dataclass(frozen=True)
class MediaApi:
    """The media library the picker uses, as the browser needs to see it."""

    prefix: str
    search_param: str | None = None
    public_files: bool = False
    """Whether ``AuthMiddleware`` lets an anonymous ``GET`` of a file through.
    Necessary for the pagebuilder widget to render an image, not sufficient:
    a route can still demand a permission of its own (``file_storage``'s
    download does), which no registry can answer for."""

    @property
    def file_url_template(self) -> str:
        return f"{self.prefix}/files/{ID_PLACEHOLDER}/download"

    def props(self) -> dict[str, Any]:
        """The ``media_api`` view prop. Paths, not URLs: same-origin by rule
        (:func:`~sm_records.settings_checks.check_media_api_prefix`)."""
        return {
            "prefix": self.prefix,
            "list_path": f"{self.prefix}/files",
            "upload_path": f"{self.prefix}/upload",
            "file_url_template": self.file_url_template,
            "meta_url_template": f"{self.prefix}/files/{ID_PLACEHOLDER}",
            "search_param": self.search_param,
        }


def _routes(app: Any) -> list[tuple[str, frozenset[str], Any]]:
    """``(path, methods, route)`` for every routed endpoint on the app.

    Through ``iter_route_contexts`` where FastAPI has it: since the release
    that made ``include_router`` lazy, ``app.routes`` holds one opaque entry
    per included router and none of its routes (the sibling modules' tests
    read the OpenAPI schema for the same reason). That is not an option at
    startup — building the schema caches it before later hooks mount theirs.
    An older FastAPI copied every route up, so ``app.routes`` is the list.
    """
    routes = list(getattr(app, "routes", ()))
    found = []
    for route in _iter_route_contexts(routes) if _iter_route_contexts else routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and methods:
            found.append((path, frozenset(methods), route))
    return found


def _candidates(app: Any) -> list[str]:
    """Every prefix under which the four ``file_storage`` routes all exist."""
    routes = _routes(app)
    found: list[str] = []
    for path, methods, _ in routes:
        match = _DOWNLOAD_RE.match(path)
        if not match or "GET" not in methods or match.group("prefix") in found:
            continue
        prefix = match.group("prefix")
        tails = [(p[len(prefix) :], m) for p, m, _ in routes if p.startswith(f"{prefix}/")]
        if (
            any(tail == "/upload" and "POST" in m for tail, m in tails)
            and any(tail == "/files" and "GET" in m for tail, m in tails)
            and any(_FILE_RE.match(tail) and "GET" in m for tail, m in tails)
        ):
            found.append(prefix)
    return found


def _registered_prefix(app: Any) -> str | None:
    """``meta.route_prefix`` of the host's ``FileStorage`` module, if any."""
    modules = getattr(getattr(getattr(app, "state", None), "sm", None), "modules", ()) or ()
    for module in modules:
        meta = getattr(module, "meta", None)
        if getattr(meta, "name", None) == MEDIA_MODULE_NAME:
            prefix = getattr(meta, "route_prefix", None)
            return prefix.rstrip("/") if isinstance(prefix, str) and prefix else None
    return None


def detect_prefix(app: Any) -> str | None:
    """The media API prefix mounted on ``app``, or ``None`` — see the module
    docstring for the rule."""
    found = _candidates(app)
    registered = _registered_prefix(app)
    if registered is not None and registered in found:
        return registered
    if len(found) == 1:
        return found[0]
    if found:
        logger.warning(
            "records: several media APIs are mounted (%s); the media field picker is off "
            "until media_api_prefix names one on the Settings screen.",
            ", ".join(found),
        )
    return None


def _search_param(app: Any, prefix: str) -> str | None:
    """The filename-search query parameter the list route declares, if any."""
    for path, methods, route in _routes(app):
        if path != f"{prefix}/files" or "GET" not in methods:
            continue
        dependant = getattr(route, "dependant", None)
        names = {param.name for param in getattr(dependant, "query_params", ())}
        return next((name for name in _SEARCH_PARAMS if name in names), None)
    return None


def _public_files(app: Any, prefix: str) -> bool:
    registry = getattr(getattr(app, "state", None), "public_routes", None)
    if registry is None:
        # No auth middleware at all: nothing gates the route, but nothing says
        # it is meant to be public either. Only an explicit exemption counts.
        return False
    probe = f"{prefix}/files/{_PROBE_ID}/download"
    return bool(registry.matches("GET", probe))


def resolve(app: FastAPI, prefix_setting: str | None) -> MediaApi | None:
    """The media API for this boot: the setting when it names one, detection
    when it is ``None``, nothing when it is ``""``."""
    try:
        prefix_setting = check_media_api_prefix(prefix_setting)
    except ValueError as exc:
        # Refused at save, so only a row written around the validator gets
        # here — and ``on_startup`` is the wrong place to raise about it (see
        # ``boot.public_prefix``). Detection is the safe reading of a bad value.
        logger.error("records: stored media_api_prefix is invalid (%s); detecting instead.", exc)
        prefix_setting = None
    if prefix_setting == "":
        logger.info("records: media_api_prefix is empty; the media field picker is off.")
        return None
    prefix = prefix_setting if prefix_setting is not None else detect_prefix(app)
    if prefix is None:
        return None
    if prefix_setting is not None and prefix not in _candidates(app):
        # Not refused: the operator may be pointing at an API this app proxies
        # rather than mounts. Said once, because a typo looks exactly like this.
        logger.warning(
            "records: media_api_prefix %r does not match a media API mounted on this app; "
            "the picker will call it anyway.",
            prefix,
        )
    return MediaApi(
        prefix=prefix,
        search_param=_search_param(app, prefix),
        public_files=_public_files(app, prefix),
    )


def configure(app: FastAPI, prefix_setting: str | None) -> MediaApi | None:
    """Resolve the media API and park it on the services container, where
    :func:`media_props` and the public read API look for it."""
    media_api = resolve(app, prefix_setting)
    services = getattr(app.state, constants.PACKAGE, None)
    if services is not None:
        services.media_api = media_api
    return media_api


def current(app: Any) -> MediaApi | None:
    services = getattr(getattr(app, "state", None), constants.PACKAGE, None)
    return getattr(services, "media_api", None)


def media_props(request: Request) -> dict[str, Any] | None:
    """The ``media_api`` prop of the editor and list screens: ``None`` when
    this install has no media library, and the ``media`` field is a text box."""
    media_api = current(request.app)
    return None if media_api is None else media_api.props()


def public_file_url_template(request: Request) -> str | None:
    """What the anonymous read API advertises for rendering a ``media`` value:
    the download URL template when files are exempt from authentication, and
    ``None`` otherwise — on a stock host, always ``None``, because
    ``file_storage`` registers no public route."""
    media_api = current(request.app)
    return media_api.file_url_template if media_api and media_api.public_files else None
