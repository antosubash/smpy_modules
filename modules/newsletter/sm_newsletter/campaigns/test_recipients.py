"""Who a test send may go to (#348).

A test send carries the campaign's own HTML from the install's sender, so it
goes only to people the caller can vouch for:

* the caller's own address (``request.state.user.email``, the signed-in user);
* active users who belong to the campaign's tenant: found through the
  framework's :class:`~simple_module_core.user_directory.UserDirectory` (an
  exact, case-insensitive address match on an active account) and, on a
  multi-tenant host, kept only when
  :func:`~simple_module_core.tenancy.tenant_member_ids` says they are members
  of the tenant newsletter bound (the resolved one, never ``user.tenant_id``).
  A single-tenant host, where nothing upstream resolved another tenant, has
  one organisation, so every active account belongs to it. No directory, or on
  a multi-tenant host no membership store, means nobody is vouched for (fail
  closed);
* the addresses in ``test_send_extra_recipients`` (a shared review inbox).

Anything else answers ``recipient_not_allowed`` for that address and is not
sent.

**One form.** Every comparison is on
:func:`~sm_newsletter.core.suppression.hashing.normalise_email`, the form
suppression hashes use too, so a spelling variant (case, a fullwidth letter,
punycode) of an allowed address is allowed.

The suppression check (``complaint`` and ``unsubscribed`` in the tenant) is
:func:`~sm_newsletter.campaigns.test_send.send_test`'s, because it runs on the
same session as the rest of the send.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import NullUserDirectory, get_user_directory
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.suppression.hashing import normalise_email
from sm_newsletter.core.tenancy import DEFAULT_TENANT, TenancyMode, mode_of, request_mode

__test__ = False  # a module named test_*, not a pytest test module

__all__ = ["DIRECTORY_SCAN", "allowed_recipients"]

DIRECTORY_SCAN = 20
"""Directory rows read per address: the search is a substring match, so an
address can share its text with a few longer ones; the exact match is kept."""


def _key(address: object) -> str:
    """``address`` in the canonical form, or "" for something that is not one."""
    try:
        return normalise_email(address)
    except ValueError:
        return ""


def _single_tenant(request: Any, tenant_id: str) -> bool:
    """True only for a single-tenant host where nothing upstream resolved another
    tenant (images' share picker applies the same test). Anything else filters
    by membership."""
    if request_mode(request, mode_of(request.app)) is not TenancyMode.SINGLE:
        return False
    upstream = getattr(request.state, "tenant_id", None)
    return upstream in (None, DEFAULT_TENANT) and tenant_id == DEFAULT_TENANT


async def _members(
    request: Any, db: AsyncSession, tenant_id: str, wanted: Sequence[str]
) -> set[str]:
    """The recipients among ``wanted`` that are active accounts in the tenant."""
    directory = get_user_directory(request.app)
    if not wanted or isinstance(directory, NullUserDirectory):
        return set()
    users: dict[str, str] = {}  # user id -> recipient
    for recipient in wanted:
        key = _key(recipient)
        for term in dict.fromkeys((recipient, key)):
            for user in await directory.search(db, term, limit=DIRECTORY_SCAN):
                if user.is_active and _key(user.email) == key:
                    users[user.id] = recipient
    if not users or _single_tenant(request, tenant_id):
        return set(users.values())
    members = await tenant_member_ids(request.app, db, tenant_id, list(users))
    return {users[uid] for uid in members or set() if uid in users}


async def allowed_recipients(
    request: Any,
    db: AsyncSession,
    *,
    tenant_id: str,
    recipients: Sequence[str],
    settings: NewsletterSettings,
) -> frozenset[str]:
    """The addresses among ``recipients`` a test may go to."""
    vouched = {_key(getattr(getattr(request.state, "user", None), "email", None))}
    vouched.update(_key(a) for a in settings.test_send_extra_recipients)
    vouched.discard("")
    allowed = {r for r in recipients if _key(r) in vouched}
    allowed |= await _members(request, db, tenant_id, [r for r in recipients if r not in allowed])
    return frozenset(r for r in recipients if r in allowed)
