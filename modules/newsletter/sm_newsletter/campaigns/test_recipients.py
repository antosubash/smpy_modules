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

**Spellings.** The address parser normalises a domain (a fullwidth ``e``
becomes ``e``) while suppression hashes, directory rows and the allow-list
keep whatever was stored, stripped and lower-cased (``normalise_email``, the
store's one normaliser). So an address is compared in both forms on both
sides: :func:`spellings` maps each recipient to every form it was submitted
in, and :func:`forms` gives a stored address's two forms.

The suppression check (``complaint`` and ``unsubscribed`` in the tenant) is
:func:`~sm_newsletter.campaigns.test_send.send_test`'s, because it runs on the
same session as the rest of the send.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import NullUserDirectory, get_user_directory
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.suppression.hashing import normalise_email
from sm_newsletter.core.tenancy import DEFAULT_TENANT, TenancyMode, mode_of, request_mode

__test__ = False  # a module named test_*, not a pytest test module

__all__ = ["DIRECTORY_SCAN", "allowed_recipients", "canonical", "forms", "spellings"]

DIRECTORY_SCAN = 20
"""Directory rows read per address: the search is a substring match, so an
address can share its text with a few longer ones; the exact match is kept."""


_ADDRESS: TypeAdapter[str] = TypeAdapter(EmailStr)


def canonical(address: object) -> str | None:
    """The address parser's form of ``address`` (stripped, lower-cased first), or None."""
    try:
        return str(_ADDRESS.validate_python(normalise_email(address)))
    except (ValidationError, ValueError):
        return None


def forms(address: object) -> frozenset[str]:
    """``address`` as stored (``normalise_email``) and as parsed; empty if neither."""
    try:
        stored = {normalise_email(address)}
    except ValueError:
        return frozenset()
    parsed = canonical(address)
    return frozenset(stored | ({parsed} if parsed else set()))


def spellings(raw: object) -> dict[str, frozenset[str]]:
    """Each parsed recipient -> every form it was submitted in, itself included."""
    out: dict[str, set[str]] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str) and (parsed := canonical(item)) is not None:
            out.setdefault(parsed, {parsed}).add(normalise_email(item))
    return {k: frozenset(v) for k, v in out.items()}


def _single_tenant(request: Any, tenant_id: str) -> bool:
    """True only for a single-tenant host where nothing upstream resolved another
    tenant (images' share picker applies the same test). Anything else filters
    by membership."""
    if request_mode(request, mode_of(request.app)) is not TenancyMode.SINGLE:
        return False
    upstream = getattr(request.state, "tenant_id", None)
    return upstream in (None, DEFAULT_TENANT) and tenant_id == DEFAULT_TENANT


async def _members(
    request: Any, db: AsyncSession, tenant_id: str, wanted: dict[str, frozenset[str]]
) -> set[str]:
    """The recipients among ``wanted`` (recipient -> its spellings) that are
    active accounts in the tenant."""
    directory = get_user_directory(request.app)
    if not wanted or isinstance(directory, NullUserDirectory):
        return set()
    users: dict[str, str] = {}  # user id -> recipient
    for recipient, names in wanted.items():
        for name in sorted(names):
            for user in await directory.search(db, name, limit=DIRECTORY_SCAN):
                if user.is_active and forms(user.email) & names:
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
    submitted: Mapping[str, frozenset[str]] | None = None,
) -> frozenset[str]:
    """The addresses among ``recipients`` (already parsed) a test may go to.

    ``submitted`` maps a recipient to the forms it was submitted in
    (:func:`spellings`); a recipient matches when any of them does."""
    names = {r: frozenset({r}) | (submitted or {}).get(r, frozenset()) for r in recipients}
    vouched: set[str] = set(forms(getattr(getattr(request.state, "user", None), "email", None)))
    for address in settings.test_send_extra_recipients:
        vouched |= forms(address)
    allowed = {r for r, n in names.items() if n & vouched}
    rest = {r: n for r, n in names.items() if r not in allowed}
    allowed |= await _members(request, db, tenant_id, rest)
    return frozenset(r for r in recipients if r in allowed)
