"""Building a LIKE pattern that means what it says.

Its own module because both the public article filter (``query_filters``) and
the admin cross-section search (``search_service``) need it, and the lower of
the two should not have to import the higher to get it.
"""

from __future__ import annotations

#: Passed as ``escape=`` alongside every pattern this module builds.
LIKE_ESCAPE = "\\"


def like_pattern(q: str) -> str:
    """A LIKE pattern matching ``q`` literally, wildcards and all.

    Every caller must also pass ``escape=LIKE_ESCAPE`` to the ``like``/``ilike``
    that consumes this. Without the ESCAPE clause SQLite reads the backslashes
    below as ordinary characters, so the pattern demands a literal backslash
    that real content never contains and the search returns nothing at all —
    strictly worse than the over-matching the escaping was added to prevent,
    and silent either way.
    """
    escaped = q.strip().translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))
    return f"%{escaped}%"
