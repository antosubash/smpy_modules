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

__all__ = ["max_expand_chars", "parse_expand"]


def _settings(request: Request) -> RecordsSettings:
    """``deps.get_settings``, imported at call time.

    :mod:`sm_records.deps` imports this module (through ``_grammar``, which
    re-exports it and shares this accessor), so naming it at module scope
    would be a cycle. One accessor and not a second copy of
    ``request.app.state.sm_records.settings``: the caps are settings-screen
    values like every other, and a stale second reader is how a limit starts
    depending on which dependency asked.
    """
    from sm_records.deps import get_settings

    return get_settings(request)


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _prefixes(parts: list[str]) -> list[str]:
    """``["a", "b", "c"]`` -> ``["a", "a.b", "a.b.c"]``."""
    return [".".join(parts[: index + 1]) for index in range(len(parts))]


def max_expand_chars(settings: RecordsSettings) -> int:
    """The longest ``?expand=`` (all values together) that could name a
    request the other caps allow: ``max_expand_paths`` terms, each
    ``max_expand_depth`` keys of ``MAX_KEY_LEN`` plus their separators.

    Checked before the string is split, so a request of a hundred thousand
    ``a,a,a,…`` terms is refused in one ``len`` instead of being parsed first —
    every later check is per term, and without this bound the term count is
    the client's to choose.
    """
    return settings.max_expand_paths * settings.max_expand_depth * (constants.MAX_KEY_LEN + 1)


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

    Every refusal is a ``400`` naming the parameter, and each is decided
    as soon as the term that crosses it is read: a value longer than
    :func:`max_expand_chars` (before anything is split), an empty segment
    (``a..b``, ``.a``), a segment longer than any key can be, a path deeper
    than ``max_expand_depth``, and more distinct hops than
    ``max_expand_paths``. Duplicates and hops are tracked in sets, so the work
    is linear in the (already bounded) input.
    """
    limit = max_expand_chars(settings)
    total = sum(len(raw) for raw in raw_expand)
    if total > limit:
        raise _refuse(f"'expand' is {total} characters long, at most {limit}")
    paths: list[str] = []
    seen: set[str] = set()
    hops: set[str] = set()
    for raw in raw_expand:
        for item in raw.split(","):
            path = item.strip()
            if not path or path in seen:
                continue
            parts = path.split(".")
            if not all(parts):
                raise _refuse(f"malformed 'expand' path {path!r}: empty segment")
            if any(len(part) > constants.MAX_KEY_LEN for part in parts):
                raise _refuse(
                    f"malformed 'expand' path {path!r}: a segment is longer than "
                    f"{constants.MAX_KEY_LEN} characters"
                )
            if len(parts) > settings.max_expand_depth:
                raise _refuse(
                    f"'expand' path {path!r} is {len(parts)} levels deep, "
                    f"at most {settings.max_expand_depth}"
                )
            hops.update(_prefixes(parts))
            if len(hops) > settings.max_expand_paths:
                raise _refuse(
                    f"too many 'expand' hops: more than {settings.max_expand_paths} named"
                )
            seen.add(path)
            paths.append(path)
    return paths
