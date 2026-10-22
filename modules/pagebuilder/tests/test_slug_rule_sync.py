"""The editor's slug check is the API's, copied (#188).

``utils/slugRule.ts`` checks a slug on every keystroke with a hand copy of the
schema's pattern and length; this fails when the schema moves and the copy
does not.
"""

from __future__ import annotations

import re
from pathlib import Path

from pagebuilder.contracts.schemas import _pages
from pagebuilder.contracts.schemas._pages import PageCreate

_RULE = Path(_pages.__file__).resolve().parents[2] / "utils" / "slugRule.ts"


def _constraint(name: str) -> object:
    field = PageCreate.model_fields["slug"]
    return next(getattr(m, name) for m in field.metadata if getattr(m, name, None) is not None)


def test_the_editor_pattern_is_the_schema_pattern() -> None:
    copied = re.search(r"SLUG_PATTERN = /(.+)/;", _RULE.read_text(encoding="utf-8"))

    assert copied is not None
    assert copied.group(1) == _constraint("pattern")


def test_the_editor_length_is_the_schema_length() -> None:
    copied = re.search(r"SLUG_MAX_LENGTH = (\d+);", _RULE.read_text(encoding="utf-8"))

    assert copied is not None
    assert int(copied.group(1)) == _constraint("max_length")
