"""The registered presets, and applying one to a collection (spec §8.1).

A preset *seeds* a collection: what it brings stays editable afterwards, and
applying it again changes nothing that is already there. So
:func:`apply_preset` is idempotent:

* **prompts** - one per :class:`~sm_images.pipeline.presets.PromptSpec`,
  recognised by ``Prompt.preset_prompt_id`` (unique per collection in the
  database too). A spec already applied is left as it is, edits included; a
  group spec's member is the prompt made from its ``member`` spec. A name a
  prompt of the collection already has refuses the whole application (409
  ``prompt_name_taken``), so nothing is half applied;
* **pipeline** - each step the preset configures and the collection does not
  is added (enabled, with the preset's params); a step already there keeps
  the collection's settings. The result is saved only if it validates
  strictly, like a pipeline save (422 ``invalid_pipeline_config``);
* **group roles** - set only while the collection has none;
* ``Collection.preset_id`` - the preset, whose cross-check group runs call.

Applying can switch ``auto_run`` on, which spends AI requests on every new
image: the route is the owner's or a manager's.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from sm_images.access import redaction
from sm_images.ai import codes
from sm_images.errors import Invalid, NotFound
from sm_images.map import revoke
from sm_images.models import Collection, Prompt
from sm_images.models.enums import PromptScope
from sm_images.pipeline import registry
from sm_images.pipeline.extensions import load_extensions
from sm_images.pipeline.presets import Preset, PromptSpec
from sm_images.schemas.prompt import PromptCreate
from sm_images.services import prompts as prompt_service

__all__ = ["apply_preset", "list_presets", "preset_out"]

CODE_INVALID_CONFIG = "invalid_pipeline_config"


def list_presets() -> list[Preset]:
    load_extensions()  # a no-op once the registry is frozen
    return [p for _, p in sorted(registry.all_presets().items())]


def preset_out(preset: Preset) -> dict[str, Any]:
    return {
        "id": preset.id,
        "label_key": preset.label_key,
        "pipeline": preset.pipeline,
        "group_roles": preset.group_roles,
        "filename_patterns": preset.filename_patterns,
        "prompts": [
            {
                "id": spec.id,
                "name": spec.label,
                "scope": spec.scope,
                "inputs": spec.inputs if spec.scope == "image" else spec.group_inputs(),
                "member": spec.member,
                "auto_run": spec.auto_run,
                "instruction": spec.instruction,
                "output_schema": spec.output_schema,
            }
            for spec in preset.prompts
        ],
        "has_cross_check": preset.cross_check is not None,
    }


def _get(preset_id: str) -> Preset:
    load_extensions()
    found = registry.get_preset(preset_id)
    if found is None:
        raise NotFound("no such preset is installed", code=codes.CODE_PRESET_NOT_FOUND)
    return found


async def _prompts(db: Any, collection: Collection, preset: Preset) -> list[Prompt]:
    stmt = select(Prompt).where(
        Prompt.collection_id == collection.id,
        Prompt.preset_prompt_id.in_([s.id for s in preset.prompts]),
    )
    have = {p.preset_prompt_id: p for p in (await db.execute(stmt)).scalars()}
    todo = [s for s in preset.prompts if s.id not in have]
    if todo:
        names = [s.label for s in todo]
        taken = select(Prompt.name).where(
            Prompt.collection_id == collection.id, Prompt.name.in_(names)
        )
        if (await db.execute(taken)).first() is not None:
            raise prompt_service.name_taken()
    created: list[Prompt] = []
    # Image specs first: a group spec's member must exist when it is created.
    for spec in sorted(todo, key=lambda s: s.scope != "image"):
        member = have[spec.member].id if spec.member in have else None
        row = await prompt_service.create(
            db,
            collection,
            _body(spec, member),
            preset_id=preset.id,
            preset_prompt_id=spec.id,
        )
        have[spec.id] = row
        created.append(row)
    return created


def _body(spec: PromptSpec, member: Any) -> PromptCreate:
    group = spec.scope == "group"
    return PromptCreate(
        name=spec.label,
        scope=PromptScope.GROUP if group else PromptScope.IMAGE,
        instruction=spec.instruction,
        output_schema=spec.output_schema,
        inputs=spec.group_inputs() if group else None,
        member_prompt_id=member,
        auto_run=spec.auto_run,
    )


async def _pipeline(db: Any, collection: Collection, preset: Preset) -> None:
    from sm_images.ai import prompt_steps
    from sm_images.pipeline.config import (
        PipelineConfigError,
        protect_originals,
        validate_pipeline_config,
    )

    steps = dict((collection.pipeline_config or {}).get("steps") or {})
    added = {sid: {**params} for sid, params in preset.pipeline.items() if sid not in steps}
    if not added:
        return
    config = {"steps": {**steps, **added}}
    prompts = await prompt_steps.resolve(db, collection.id, tenant=collection.tenant_id)
    try:
        parsed = validate_pipeline_config(config, strict=True, prompts=prompts)
    except PipelineConfigError as exc:
        raise Invalid(str(exc)[:1000], code=CODE_INVALID_CONFIG) from exc
    collection.pipeline_config = config
    collection.protect_originals = protect_originals(collection.protect_originals, parsed)


async def apply_preset(db: Any, collection: Collection, preset_id: str) -> list[Prompt]:
    """Seed ``collection`` from the preset (see the module docstring); returns
    the prompts it created - none the second time. The caller's session."""
    preset = _get(preset_id)
    created = await _prompts(db, collection, preset)
    gate = redaction.gate_key(collection)
    await _pipeline(db, collection, preset)
    if not collection.group_roles and preset.group_roles:
        collection.group_roles = list(preset.group_roles)
    collection.preset_id = preset.id
    await db.flush()
    await revoke.gate_saved(db, collection, gate)  # a preset enabling a mutator
    return created
