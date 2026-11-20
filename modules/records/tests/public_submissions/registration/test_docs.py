"""The registration doc names the states the code really has."""

from __future__ import annotations

import re
from pathlib import Path

from sm_events.core.constants import REGISTRATION_STATES

DOC = Path(__file__).resolve().parents[3] / "docs" / "registration.md"


def test_the_doc_lists_only_real_public_states():
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    sentence = re.search(r"the states are (.*?) only", text)
    assert sentence, "the sentence about the public states moved"
    named = set(re.findall(r"`([a-z_]+)`", sentence.group(1)))
    assert named, sentence.group(1)
    assert named <= set(REGISTRATION_STATES), named - set(REGISTRATION_STATES)
    assert "ended" not in text.split("the states are")[1][:200]
