"""Which published pages another module serves the public URL for.

A page's public address is normally ``{public_route_prefix}/{slug}`` and this
module owns it. But a page can also be the body of something a *neighbouring*
module presents — a news article, say — and that module will want its own
address for it. Two addresses for one document is a duplicate-content problem
and an ambiguous "where does this live" for everybody reading the site.

So a module that presents pages registers a claim here. The effect is narrow
and entirely about URLs:

* the public viewer refuses a claimed slug, so the page answers at exactly one
  address — the claimant's;
* the sitemap advertises the claimant's address instead of this module's, so a
  crawler is never sent to the address the viewer just refused.

Nothing here knows what a claimant *is*. A claim is a callable that turns slugs
into public paths, and pagebuilder learns nothing about the module that
registered it beyond that.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

SlugClaim = Callable[[AsyncSession, Sequence[str], str], Awaitable[Mapping[str, str]]]
"""Given slugs *in one locale*, return ``{slug: public_path}`` for the ones this
claimant owns.

Bulk rather than one slug at a time because the sitemap asks about every
published page at once, and a per-slug callback would make a crawl N queries
deep. The viewer passes a single-element sequence.

The locale is a separate argument rather than folded into the key because a
claimant answers about one language at a time — slugs are only unique within
one, so a bare slug does not identify a page — and because the path it returns
has to carry that language's prefix.

Slugs the claimant does not own are simply absent from the mapping.
"""

_claims: list[SlugClaim] = []


def register(claim: SlugClaim) -> None:
    """Register a claim. Called from a module's startup hook."""
    _claims.append(claim)


def reset() -> None:
    """Forget every claim.

    Module registration is process-global, so a test that boots an app with a
    claimant would otherwise leak it into every later test in the same process.
    """
    _claims.clear()


async def resolve(
    db: AsyncSession, slugs: Sequence[str], locale: str
) -> dict[str, str]:
    """``{slug: public_path}`` across every registered claim, within ``locale``.

    Earlier claims win on the same slug. Two modules claiming one page is a
    misconfiguration rather than something to arbitrate here, and picking a
    stable winner beats letting registration order decide silently.
    """
    resolved: dict[str, str] = {}
    if not slugs:
        return resolved
    for claim in _claims:
        for slug, url in (await claim(db, slugs, locale)).items():
            resolved.setdefault(slug, url)
    return resolved


async def claimed_url(db: AsyncSession, slug: str, locale: str) -> str | None:
    """Where one slug actually serves, or ``None`` if this module still owns it."""
    return (await resolve(db, [slug], locale)).get(slug)
