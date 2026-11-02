# Writing a plugin

A plugin adds **steps** (work done per image), **presets** (a bundle of pipeline,
prompts, group roles and a cross-check) and **result views** (how the console
shows a step's output). It is an ordinary framework module: a Python package with
a `simple_module` entry point and, for images, one extra file. There is no second
plugin mechanism and no entry-point group of its own.

No-code customisation does not need a plugin at all. An owner can write a prompt
(an instruction plus a JSON Schema) on the prompt manager screen; the correction
form in the review queue is generated from that schema. Use a plugin for what a
prompt cannot express (a deterministic per-image computation, an external
service) or to ship a preset with a product.

## Registration

The plugin's package ships `images_extensions.py` with

```python
def register(registry) -> None: ...
```

`registry` offers `register_step(step)` and `register_preset(preset)`.

**Why a file and not `on_startup`.** Celery workers never build the app or run
module hooks, and in the web process a dependant's `on_startup` runs after
images' own. A file that images imports itself runs the same way everywhere.
`sm_images.pipeline.extensions.load_extensions()` registers the built-in steps,
then, for every installed `simple_module` entry point whose package has an
`images_extensions` submodule, imports it and calls `register`, then **freezes**
the registry. The web app calls it in images' `on_startup`; a worker calls it
the first time it needs the registry. Both run one code path, so both see the
same registry.

- **Install it identically in the web image and in every worker image.** A worker
  without the plugin settles the plugin's step runs as `not_installed`, and a
  worker with a different version registers a different step.
- `register_step` or `register_preset` called outside `load_extensions` (after
  the freeze) raises `RegistryFrozenError`.
- A package with no `images_extensions` is skipped. A plugin whose own package
  fails to import is a broken install and fails loudly; a failed load empties the
  registry so a retry starts clean.
- Registration problems fail at boot, not on the first job: a duplicate id, a
  reserved id, a step missing a protocol attribute, an unresolvable or cyclic
  `requires` (checked at the freeze), a preset whose prompt schema the schema
  checker refuses.

The module class only declares the dependency. Its name is `Images`:

```python
# my_plugin/module.py
from simple_module_core.module import ModuleBase, ModuleMeta


class MyPluginModule(ModuleBase):
    meta = ModuleMeta(name="MyPlugin", depends_on=["Images"])
```

```toml
# pyproject.toml
[project.entry-points.simple_module]
my_plugin = "my_plugin.module:MyPluginModule"
```

## A step

```python
# my_plugin/images_extensions.py
import io

from PIL import Image
from pydantic import BaseModel
from sm_images.contracts import Preset, PromptSpec, StepOutcome


class Params(BaseModel):
    pass


class CountPixels:
    id = "my_plugin.count_pixels"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = False
    queue = "images"

    def params_schema(self):
        return Params

    def applies(self, image, params) -> bool:
        return True

    async def run(self, ctx):
        with Image.open(io.BytesIO(await ctx.read_display())) as img:
            width, height = img.size
        return StepOutcome.completed({"pixels": width * height})


def register(registry) -> None:
    registry.register_step(CountPixels())
```

| Attribute | Rule |
| --- | --- |
| `id` | `<plugin>.<name>`, lowercase `[a-z0-9_]`, unique. `exif`, `renditions`, `quality`, `anonymize`, `classify` and every `prompt:` id are reserved |
| `version` | A positive integer. **Bump it to make completed runs stale**; the collection then offers a re-run |
| `requires` | Ids that must be completed (or ordinarily skipped) first. May name built-ins or other plugins' steps. A requirement a collection has not enabled settles the step as `dependency_unavailable` |
| `mutates_display` | `True` if the step writes a display copy. At most one such step may be enabled per collection; the pipeline save refuses a second |
| `sends_display_out` | Optional, default `False`. Set it to `True` if the step sends the display copy outside the system. It is then ordered after the display mutator, and the executor fails the run `display_not_ready`, without calling `run`, when the copy is not trustworthy. **Set it if you call an external service** |
| `queue` | `images`, `images_heavy` or `images_gpu`. Route a step that needs torch or similar to a worker that has it |
| `params_schema()` | A Pydantic model. The pipeline screen renders it as the per-collection form, the save validates against it, and the executor validates again before each run |
| `applies(image, params)` | `False` settles the run as `skipped` (`not_applicable`) |
| `run(ctx)` | Returns `StepOutcome.completed(output)`, `.skipped(reason)` or `.failed(code, message)` |

`ctx` is a `StepContext`:

- `ctx.image` is an `ImageRead` (metadata only, no ORM object and no storage
  keys), `ctx.params` the validated params, `ctx.tenant_id` the tenant.
- `await ctx.read_display()` and `await ctx.read_original()` return bytes.
- `await ctx.write_display(data, content_type)` stages a new display copy. It
  works only if `mutates_display` is true (`DisplayNotAllowed` otherwise). The
  copy is published only if the run's lease still holds when it completes, and
  the original is never touched. Steps never reach storage or a session
  directly.
- `await ctx.progress(pct)` renews the lease and tells the task sweep the step is
  alive. **It must be awaited**; an un-awaited call renews nothing and the lease
  expires under a step that is still working. It raises the executor's lost-lease
  error if another worker has reclaimed the run: stop, the result would be
  discarded.

The output must be JSON and at most `step_output_max_bytes` (64 KiB by
default). Editors see it in the image viewer; viewers do not.

A step raising is a `failed` run with a bounded message, and a failed step does
not block independent steps.

## A preset

```python
def register(registry) -> None:
    registry.register_step(CountPixels())
    registry.register_preset(
        Preset(
            id="my_plugin",
            label_key="my_plugin.preset.label",
            pipeline={"my_plugin.count_pixels": {}},
            group_roles=["centre", "left", "right"],
            filename_patterns=[r"^(?P<group>.+?)_(?P<role>centre|left|right)"],
            prompts=[
                PromptSpec(
                    id="my_plugin.photo",
                    name="Trees per photo",
                    instruction="Count the trees.",
                    output_schema={
                        "type": "object",
                        "properties": {"trees": {"type": "integer"}},
                        "required": ["trees"],
                    },
                    auto_run=True,
                ),
                PromptSpec(
                    id="my_plugin.summary",
                    name="Trees per site",
                    scope="group",
                    inputs="results",
                    instruction="Summarise the site.",
                    output_schema={
                        "type": "object",
                        "properties": {"trees": {"type": "integer"}},
                        "required": ["trees"],
                    },
                ),
            ],
            cross_check=agreement,
        )
    )
```

- A preset id matches `[a-z][a-z0-9_]*` and is unique. `label_key` is a key in the
  plugin's own locale catalogue.
- `pipeline` maps step ids to params and seeds `pipeline_config`; `group_roles`
  seeds the collection's role order; `filename_patterns` use the named groups
  `group` and an optional `role`.
- A `PromptSpec` id is dotted (`[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*`). A group
  prompt cannot `auto_run`. A group prompt over `results` or `both` names its
  image spec in `member`, which may be omitted when the preset has exactly one
  image spec. A preset's checks run when it is built, and `register_preset` runs
  every schema through the schema checker, refusing an unsafe one at boot.
- **Applying** a preset to a collection is `POST
  /api/images/collections/{id}/apply-preset` (owner or `images.manage`). It is
  idempotent and the values stay editable afterwards. See
  [pipeline.md](pipeline.md#presets).

**A cross-check** is `cross_check(group, results) -> dict`, a pure function over
read models, called after a group prompt run with no session open. `group` is a
`GroupRead` with its members in role order; `results` are the usable member
results in role order, then the group's own summary last (`group_id` set). The
hook gets deep copies. Its return value is stored on the group result;
an exception, a value that is not a JSON-serialisable dict, or one over
`step_output_max_bytes` is stored as `{"error": "..."}` instead.

The module ships no presets.

## When a plugin is removed

A collection whose preset or enabled step is no longer registered still loads.
The step is kept in its configuration as `not_installed`, its stored results stay
readable, the console says so, and the step is never scheduled. Re-installing the
plugin resumes it: `images.reconcile` reopens placeholder runs of a step that is
enabled and installed again.

If the removed step was the collection's **display mutator**, the collection's
displays are **withheld until the owner re-saves the pipeline** without it,
because nothing can vouch that the copies are redacted
([access.md](access.md#withheld-images)). Removing a plugin therefore costs
availability, by design.

## Result views (frontend)

A plugin may ship `images-steps.ts` at its package root. Images globs these in
the way pagebuilder globs `pagebuilder-blocks.ts`, so images never imports a
plugin and a host without it builds nothing dangling.

```ts
// my_plugin/images-steps.ts
import { registerResultView } from '@simple-module-py/images';

import { PixelsView } from './components/PixelsView';

registerResultView({ kind: 'step', id: 'my_plugin.count_pixels', component: PixelsView });
```

- `kind` is `step` (keyed by step id), `prompt_result` (by prompt id) or
  `cross_check` (by preset id).
- The component is rendered with `{ kind, id, output, run, image, t }` and
  renders read-only. `output` is `null` for someone who may view but not edit the
  collection. Correction stays the module's schema-generated form.
- Registering the same `(kind, id)` twice throws; a hot-reloading dev server
  re-running the module must not blank the viewer.
- Anything without a registered view falls back to a generic key/value view, so
  uninstalling a plugin's frontend never breaks the viewer.
- The view files live outside `pages/` (an `.tsx` there registers a page), and
  their strings come from the plugin's own `locales/`.

## Events, contracts and data

- Subscribe to `ImageAdded`, `ImageProcessed`, `PromptResultReviewed`,
  `CollectionVisibilityChanged` and `CollectionDeleted` (published after commit).
- Read through `sm_images.contracts` (`get_collection`, `list_collections`,
  `points`, `rendition_url`); every call names its tenant and principal, and
  results are policy-filtered. Nothing else in `sm_images` is a stable surface.
- Per-project data goes in `images_image.properties` (JSON, filled from GeoJSON
  properties or upload metadata). The module's tables are not extensible. A
  plugin that needs relational data owns its own tables keyed by `image_id` or
  `collection_id`, with its own host migration.
- Deployment-wide settings belong to the plugin's own
  `register_module_settings`; per-collection ones to `params_schema()`.
- A plugin that needs torch or similar declares it in its own package. The
  module never imports a plugin's dependencies.

## Testing a plugin

`modules/images/tests/plugin_fixture/images_testplugin/` is a working plugin
(a step, two prompts, group roles and a cross-check) and `tests/test_plugin_e2e.py`
runs it end to end. To try a
plugin in a worker without installing it, put a `.dist-info` directory with an
`entry_points.txt` on `PYTHONPATH` for the web process and for every worker, as
[worker.md](worker.md#a-local-run) describes.
