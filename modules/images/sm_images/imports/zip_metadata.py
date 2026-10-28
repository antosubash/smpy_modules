"""Parsing an archive's ``metadata.json`` without trusting it: :func:`parse_json`.

The bytes are already bounded (``zip_safety`` caps their size and counts them
against the archive's budgets). What is left is the parse itself:

* **depth** is measured *before* ``json.loads`` - over the text with its
  strings blanked out, at C speed (``re`` and ``itertools.accumulate``) - so a
  document nested past :data:`MAX_DEPTH` never reaches the recursive parser;
* every way the parser can refuse - bad UTF-8, bad JSON, an integer past
  Python's digit limit (``ValueError``), recursion - is ``metadata_invalid``,
  never an exception that would leave the job running for reconcile to retry
  forever.
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any, Final

from sm_images.imports.zip_eocd import ZipRejected

__all__ = ["MAX_DEPTH", "parse_json"]

MAX_DEPTH: Final = 32
"""Deepest nesting of objects and arrays a metadata document may use."""
_STRING: Final = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"', re.DOTALL)
_NOT_BRACKET: Final = re.compile(r"[^\[\]{}]")
_STEP: Final = {"[": 1, "{": 1, "]": -1, "}": -1}


def _depth(text: str) -> int:
    brackets = _NOT_BRACKET.sub("", _STRING.sub("", text))
    return max(itertools.accumulate(map(_STEP.__getitem__, brackets)), default=0)


def parse_json(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        if _depth(text) > MAX_DEPTH:
            raise ZipRejected("metadata_invalid")
        doc = json.loads(text)
    except ZipRejected:
        raise
    except (ValueError, RecursionError, TypeError) as exc:  # JSONDecodeError, UnicodeError too
        raise ZipRejected("metadata_invalid") from exc
    if not isinstance(doc, dict):
        raise ZipRejected("metadata_invalid")
    return doc
