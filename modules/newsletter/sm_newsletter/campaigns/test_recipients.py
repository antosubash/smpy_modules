"""Who a test send may go to (#348).

A test send carries the campaign's own HTML from the install's sender, so it
goes only to people the caller can vouch for:

* the caller's own address (``request.state.user.email``, the signed-in user);
* active users who belong to the campaign's tenant: found through the
  framework's :class:`~simple_module_core.user_directory.UserDirectory` (an
  exact, case-insensitive address match on an active account whose email is
  not reported unverified, see ``_verified``) and, on a
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

**Matching.** Addresses are compared on
:func:`~sm_newsletter.core.suppression.hashing.normalise_email`, the form
suppression keys use too: the domain is normalised as the address parser does
it (a domain spelt two ways is one DNS name), the local part only NFC and
lower-cased, so a fullwidth letter or a ligature there is another mailbox and
is not vouched for. The recipient compared is the parsed address that is then
sent.

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

__all__ = ["DIRECTORY_SCANS", "allowed_recipients"]

DIRECTORY_SCANS = (20, 100, 500)
"""How many rows a directory search reads, widened in turn. ``UserDirectory``
has no exact lookup and no offset, only a substring ``search`` with a limit, so
an address that shares its text with many longer ones is found by asking for
more until the exact match turns up or the search returns fewer rows than
asked (it ran out). An address hidden behind more than the last bound is not
vouched for (fail closed)."""


def _key(address: object) -> str:
    """``normalise_email(address)``, or "" for something that is not an address."""
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


async def _exact(directory: Any, db: AsyncSession, term: str, key: str) -> list[str]:
    """Ids of active accounts whose address is exactly ``key`` (canonical form)."""
    for limit in DIRECTORY_SCANS:
        found = await directory.search(db, term, limit=limit)
        ids = [u.id for u in found if u.is_active and _key(u.email) == key]
        if ids or len(found) < limit:
            return ids
    return []


async def _verified(directory: Any, db: AsyncSession, users: dict[str, str]) -> dict[str, str]:
    """``users`` whose email is proven. ``search`` does not report it, so each
    account is re-read with ``get_many``: ``DirectoryUser.email_verified`` must
    be ``True``; ``None`` (a provider that does not track it, e.g. Keycloak
    without the claim) is accepted, ``False`` is refused. An account the re-read
    no longer finds, or finds inactive, is dropped."""
    if not users:
        return {}
    fresh = await directory.get_many(db, list(users))
    return {
        uid: recipient
        for uid, recipient in users.items()
        if (u := fresh.get(uid)) is not None and u.is_active and u.email_verified is not False
    }


async def _members(
    request: Any, db: AsyncSession, tenant_id: str, wanted: Sequence[str]
) -> set[str]:
    """The recipients among ``wanted`` that are active accounts in the tenant."""
    directory = get_user_directory(request.app)
    if not wanted or isinstance(directory, NullUserDirectory):
        return set()
    users: dict[str, str] = {}  # user id -> recipient
    searched: set[tuple[str, str]] = set()  # each (term, key) is asked once
    for recipient in wanted:
        key = _key(recipient)
        for term in (recipient, key):
            if not key or (term, key) in searched:
                continue
            searched.add((term, key))
            users.update(dict.fromkeys(await _exact(directory, db, term, key), recipient))
    users = await _verified(directory, db, users)
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
    return frozenset(allowed)
