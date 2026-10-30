"""The classify vocabulary is stored and validated as entered (review of QA round 1).

The form splits commas and newlines when the owner types the list; the server
does not re-split a stored array, or a saved ``"forest, open canopy"`` would
change meaning on read without its results being marked stale.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.pipeline.steps.classify import LABEL_MAX, ClassifyParams


def test_a_stored_label_with_a_comma_survives_unchanged() -> None:
    params = ClassifyParams(vocabulary=["forest, open canopy", "cropland"])
    assert params.vocabulary == ["forest, open canopy", "cropland"]


def test_labels_are_trimmed_and_deduplicated() -> None:
    assert ClassifyParams(vocabulary=[" water ", "water"]).vocabulary == ["water"]


def test_a_blank_or_too_long_label_is_refused() -> None:
    for bad in ("  ", "x" * (LABEL_MAX + 1)):
        with pytest.raises(ValidationError):
            ClassifyParams(vocabulary=[bad])
