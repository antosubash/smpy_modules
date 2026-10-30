"""Parsing an archive's ``metadata.json`` without trusting it: :func:`parse_json`.

The bytes are already bounded (``zip_safety`` caps their size and counts them
against the archive's budgets). What is left is the parse itself:

* **depth** is measured *before* ``json.loads``, in one linear pass that
  tracks strings and escapes (:func:`_too_deep`) - so a document nested past
  :data:`MAX_DEPTH` never reaches the recursive parser, and no backtracking
  regex ever sees the text;
* every way the parser can refuse - bad UTF-8, bad JSON, an integer past
  Python's digit limit (``ValueError``), recursion - is ``metadata_invalid``,
  never an exception that would leave the job running for reconcile to retry
  forever.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from sm_images.ingest.imports.zip_eocd import ZipRejected

__all__ = ["MAX_DEPTH", "parse_json"]

MAX_DEPTH: Final = 32
"""Deepest nesting of objects and arrays a metadata document may use."""
_SPECIAL: Final = re.compile(r'["\\\[\]{}]')
"""One character at a time (no repetition, no backtracking): the scan below is
linear in the document, and only these characters reach Python code."""


def _too_deep(text: str) -> bool:
    """Whether objects and arrays nest past :data:`MAX_DEPTH` outside strings.
    One pass over the special characters, tracking in-string and escapes;
    stops at the first level too deep."""
    depth, in_string, escaped_at = 0, False, -1
    for match in _SPECIAL.finditer(text):
        char, at = match.group(), match.start()
        if in_string:
            if at == escaped_at:
                continue  # the character after a backslash
            if char == "\\":
                escaped_at = at + 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif char in "]}":
            depth -= 1
    return False


def parse_json(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        if _too_deep(text):
            raise ZipRejected("metadata_invalid")
        doc = json.loads(text)
    except ZipRejected:
        raise
    except (ValueError, RecursionError, TypeError) as exc:  # JSONDecodeError, UnicodeError too
        raise ZipRejected("metadata_invalid") from exc
    if not isinstance(doc, dict):
        raise ZipRejected("metadata_invalid")
    return doc
