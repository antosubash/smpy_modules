"""Shared stubs for the AI module suite.

A uniquely named module (not ``conftest``): the repo's root testpaths collect
several ``tests/`` directories without packages, so ``from conftest import
...`` resolves to whichever suite's conftest loaded first — pagebuilder's,
when run from the repo root.
"""

from __future__ import annotations

from types import SimpleNamespace

from sm_ai.core import constants
from starlette.middleware.base import BaseHTTPMiddleware


class GrantAll(BaseHTTPMiddleware):
    """Auth stub: every request is an admin holding ``ai.manage``."""

    PERMISSIONS = frozenset({constants.PERM_MANAGE})

    async def dispatch(self, request, call_next):
        request.state.user = SimpleNamespace(
            id="test-user", email="t@example.com", name="T", roles=["admin"]
        )
        request.state.resolved_permissions = set(self.PERMISSIONS)
        return await call_next(request)


class GrantSettingsEdit(GrantAll):
    """``GrantAll`` plus ``settings.edit``: may change ``allow_private_base_url``."""

    PERMISSIONS = frozenset({constants.PERM_MANAGE, constants.PERM_SETTINGS_EDIT})


def fake_dns(monkeypatch, answers: dict[str, list[str]]) -> list[str]:
    """Answer ``getaddrinfo`` from ``answers`` (host -> addresses) for the base-URL
    guard; an unknown host does not resolve. Returns the hosts looked up, in order."""
    import socket

    from sm_ai.core import url_safety

    asked: list[str] = []

    def getaddrinfo(host, port, *args, **kwargs):
        asked.append(host)
        if host not in answers:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        family = {True: socket.AF_INET6, False: socket.AF_INET}
        return [(family[":" in ip], socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers[host]]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", getaddrinfo)
    return asked
