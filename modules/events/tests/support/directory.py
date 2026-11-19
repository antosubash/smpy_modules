"""A user directory over a dict, and the role map ``build_app`` installs for it."""

from __future__ import annotations

from simple_module_core.user_directory import DirectoryUser

ROLE_MAP = {
    "viewer": ["events.view"],
    "editor": ["events.view", "events.edit"],
    "manager": ["events.view", "events.manage"],
    "admin": ["*"],
}
"""What ``build_app`` maps onto the permission registry, so a user's directory roles resolve."""


class Directory:
    """A user directory over a dict: ``{id: (email, full_name, is_active)}``.

    ``roles`` is ``{id: role names}``; a user with no entry has none, and an entry of ``None``
    is what a provider that keeps roles in the IdP reports (roles unknown). Roles are returned
    only when asked for (``with_roles=True``), as the real directory does."""

    entity_type = None

    def __init__(
        self,
        users: dict[str, tuple[str, str | None, bool]] | None = None,
        roles: dict[str, tuple[str, ...] | None] | None = None,
        verified: dict[str, bool | None] | None = None,
    ) -> None:
        self.users = users or {}
        self.roles = roles or {}
        self.verified = verified or {}
        self.get_many_calls = 0
        self.searches: list[str | None] = []

    def _user(self, uid: str, *, with_roles: bool = False) -> DirectoryUser:
        email, name, active = self.users[uid]
        roles = self.roles.get(uid, ()) if with_roles else None
        return DirectoryUser(
            id=uid,
            email=email,
            full_name=name,
            is_active=active,
            roles=roles,
            email_verified=self.verified.get(uid),
        )

    async def get_many(self, db, ids, *, with_roles=False):
        self.get_many_calls += 1
        return {i: self._user(i, with_roles=with_roles) for i in ids if i in self.users}

    async def search(self, db, term, *, limit):
        self.searches.append(term)
        needle = (term or "").lower()
        hits = [
            self._user(uid)
            for uid, (email, name, _a) in self.users.items()
            if needle in email.lower() or needle in (name or "").lower()
        ]
        return hits[:limit]

    def match_ids(self, term):
        return None
