"""The classify vocabulary takes commas as well as one label per line (QA TEST-007).

``cropland, forest`` - the format the prompt schema's "Allowed values" uses -
was stored as one label, so the model was told to answer with that string.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.steps.classify import LABEL_MAX, VOCABULARY_MAX, ClassifyParams


def test_commas_and_newlines_both_separate_labels() -> None:
    params = ClassifyParams(vocabulary=["cropland, forest,water", " grassland\nforest ", "", " , "])
    assert params.vocabulary == ["cropland", "forest", "water", "grassland"]


def test_a_too_long_label_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        ClassifyParams(vocabulary=["x" * (LABEL_MAX + 1)])


def test_the_label_cap_applies_after_splitting() -> None:
    pairs = [f"a{i},b{i}" for i in range(VOCABULARY_MAX // 2 + 1)]  # under the cap, unsplit
    with pytest.raises(ValidationError):
        ClassifyParams(vocabulary=pairs)
