"""``validate_pipeline_config``: strict for a save, lenient for the executor."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sm_images.pipeline import registry
from sm_images.pipeline.config import PipelineConfigError, validate_pipeline_config

from tests.support.pipeline import Blur, Scripted, use_steps


class _Threshold(BaseModel):
    threshold: int = 5


class Tuned(Scripted):
    def params_schema(self):
        return _Threshold


@pytest.fixture(autouse=True)
def _steps():
    second = Blur()
    second.id = "acme.paint"
    use_steps(Tuned("acme.tuned"), Blur(), second)
    yield
    registry.reset_registry()


def test_params_are_validated_and_enabled_is_not_a_param():
    cfg = validate_pipeline_config({"steps": {"acme.tuned": {"enabled": True, "threshold": 9}}})
    (step,) = cfg.steps.values()
    assert (step.state, step.params.threshold, step.runnable) == ("ok", 9, True)


def test_unknown_ids_are_kept_as_not_installed():
    cfg = validate_pipeline_config({"steps": {"gone.step": {"x": 1}, "prompt:abc": {}}})
    assert {s.id: s.state for s in cfg.steps.values()} == {
        "gone.step": "not_installed",
        "prompt:abc": "not_installed",
    }
    assert cfg.enabled() == ["gone.step", "prompt:abc"] and cfg.runnable() == []


def test_disabled_steps_are_kept_but_not_enabled():
    cfg = validate_pipeline_config({"steps": {"exif": {"enabled": False}, "renditions": {}}})
    assert cfg.enabled() == ["renditions"] and set(cfg.steps) == {"exif", "renditions"}


def test_strict_refuses_bad_params_shape_and_two_mutators():
    with pytest.raises(PipelineConfigError):
        validate_pipeline_config({"steps": {"acme.tuned": {"threshold": "lots"}}})
    with pytest.raises(PipelineConfigError):
        validate_pipeline_config({"steps": ["exif"]})
    with pytest.raises(PipelineConfigError):
        validate_pipeline_config({"steps": {"acme.blur": {}, "acme.paint": {}}})


def test_lenient_marks_what_strict_refuses():
    cfg = validate_pipeline_config(
        {"steps": {"acme.tuned": {"threshold": "lots"}, "acme.blur": {}, "acme.paint": {}}},
        strict=False,
    )
    assert {s.id: (s.state, s.error) for s in cfg.steps.values()} == {
        "acme.tuned": ("invalid", "invalid_params"),
        "acme.blur": ("invalid", "too_many_display_mutators"),
        "acme.paint": ("invalid", "too_many_display_mutators"),
    }
    assert validate_pipeline_config(["junk"], strict=False).steps == {}


def test_empty_config_enables_nothing():
    assert validate_pipeline_config({}).steps == {}
    assert validate_pipeline_config(None).enabled() == []
