"""``Preset`` and ``PromptSpec`` refuse a malformed plugin when it is built or
registered, so it fails at boot rather than when a collection applies it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.pipeline import registry
from sm_images.pipeline.presets import Preset, PromptSpec

PHOTO = PromptSpec(id="acme.photo", instruction="Look.")


def test_a_lone_image_spec_is_the_group_specs_member():
    site = PromptSpec(id="acme.site", scope="group", inputs="results", instruction="Sum.")
    preset = Preset(id="acme", label_key="acme.l", prompts=[PHOTO, site])
    assert preset.prompts[1].member == "acme.photo"
    assert preset.prompts[1].group_inputs() == "results"
    images_only = PromptSpec(id="acme.look", scope="group", instruction="Sum.")
    assert Preset(id="b", label_key="b", prompts=[images_only]).prompts[0].member is None


@pytest.mark.parametrize(
    "prompts",
    [
        # two image specs: the member must be named
        [
            PHOTO,
            PromptSpec(id="acme.other", instruction="x"),
            PromptSpec(id="acme.site", scope="group", inputs="both", instruction="x"),
        ],
        # the member is a group spec, or not in the preset
        [
            PromptSpec(
                id="acme.site", scope="group", inputs="results", member="acme.x", instruction="x"
            )
        ],
        # a member for an images-only consolidation
        [PHOTO, PromptSpec(id="acme.site", scope="group", member="acme.photo", instruction="x")],
        # duplicate ids or names
        [PHOTO, PHOTO],
        [PHOTO, PromptSpec(id="acme.b", name="acme.photo", instruction="x")],
    ],
)
def test_a_malformed_preset_is_refused(prompts):
    with pytest.raises(ValidationError):
        Preset(id="acme", label_key="acme.l", prompts=prompts)


@pytest.mark.parametrize(
    "kw",
    [
        {"id": "Bad Id", "instruction": "x"},
        {"id": "acme.x", "instruction": "x", "inputs": "results"},  # image scope
        {"id": "acme.x", "instruction": "x", "scope": "group", "auto_run": True},
        {"id": "acme.x", "instruction": ""},
    ],
)
def test_a_malformed_spec_is_refused(kw):
    with pytest.raises(ValidationError):
        PromptSpec(**kw)


def test_an_unsafe_schema_fails_registration():
    deep: dict = {"type": "string"}
    for _ in range(12):
        deep = {"type": "object", "properties": {"x": deep}}
    bad = PromptSpec(id="acme.deep", instruction="x", output_schema=deep)
    registry.reset_registry()
    try:
        with pytest.raises(registry.InvalidPresetError):
            registry.register_preset(Preset(id="acme", label_key="acme.l", prompts=[bad]))
        assert registry.get_preset("acme") is None
    finally:
        registry.reset_registry()
