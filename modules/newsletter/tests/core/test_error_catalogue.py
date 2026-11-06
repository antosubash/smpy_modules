"""Every code a ``NewsletterError`` can carry has a sentence in the catalogue (ruling C13)."""

import json
from pathlib import Path

from sm_newsletter.core import errors

CATALOGUE = Path(errors.__file__).parents[1] / "locales" / "en.json"


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def test_every_error_code_has_a_message():
    known = json.loads(CATALOGUE.read_text(encoding="utf-8"))["errors"]
    codes = {sub.code for sub in _subclasses(errors.NewsletterError)}
    assert len(codes) > 10  # the walk found the family
    assert sorted(code for code in codes if code not in known) == []
