"""``?expand=`` — the relation paths a read resolves (design §9, #81).

Split from :mod:`sm_records._grammar` for the 300-line cap; re-exported from
there and from ``deps``, so endpoints keep importing one name.

A term is a path of relation field keys joined by ``.``: ``author`` resolves
one level, ``author.publisher`` resolves the author and then the author's
publisher. Whether each key is a relation field of the type it is read on is
a question about the *schema* this dependency cannot see — it is
``services.expand``'s, answered with the same ``QueryError`` the filter grammar
refuses an unknown field with. What this layer can decide from the string
alone it decides here, before a statement runs: how deep a path reaches and how
many hops the whole request names, which together bound its statement count.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request

from sm_records import constants
from sm_records.settings import RecordsSettings

__all__ = ["expand_hops", "parse_expand"]


def _settings(request: Request) -> RecordsSettings:
    """``deps.get_settings`` at call time — ``deps`` imports this module."""
    from sm_records.deps import get_settings

    return get_settings(request)


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def expand_hops(paths: list[str]) -> set[str]:
    """Every distinct prefix of every path: ``a.b,a.c`` is ``{a, a.b, a.c}``.

    One hop is one batched statement in ``services.expand``, so this — and
    not the number of terms — is what ``max_expand_paths`` bounds.
    """
    hops: set[str] = set()
    for path in paths:
        parts = path.split(".")
        hops.update(".".join(parts[: index + 1]) for index in range(len(parts)))
    return hops


def parse_expand(
    raw_expand: list[str] = Query(default=[], alias=constants.EXPAND_PARAM),
    settings: RecordsSettings = Depends(_settings),
) -> list[str]:
    """``?expand=a,b.c`` (and ``?expand=a&expand=b.c``) — the relation paths
    to resolve on this read.

    Both spellings, because both are what a client reaches for and neither is
    ambiguous: a field key cannot contain a comma or a dot
    (``TYPE_KEY_PATTERN``). Order is preserved and duplicates are dropped
    here rather than in the service, so ``expand=a,a`` cannot cost two
    queries; ``a`` beside ``a.b`` is kept and costs nothing extra, because the
    hop ``a`` is read once either way.

    Three refusals, each a ``400`` naming the parameter: an empty segment
    (``a..b``, ``.a``), a path deeper than ``max_expand_depth``, and more
    distinct hops than ``max_expand_paths``.
    """
    paths: list[str] = []
    for raw in raw_expand:
        for item in raw.split(","):
            path = item.strip()
            if not path or path in paths:
                continue
            parts = path.split(".")
            if not all(parts):
                raise _refuse(f"malformed 'expand' path {path!r}: empty segment")
            if len(parts) > settings.max_expand_depth:
                raise _refuse(
                    f"'expand' path {path!r} is {len(parts)} levels deep, "
                    f"at most {settings.max_expand_depth}"
                )
            paths.append(path)
    hops = len(expand_hops(paths))
    if hops > settings.max_expand_paths:
        raise _refuse(f"too many 'expand' hops: {hops} named, at most {settings.max_expand_paths}")
    return paths
