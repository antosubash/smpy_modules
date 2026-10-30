# Migrating from the gis-data-portal `images` feature

The module was extracted from the portal's `features/images` and is meant to
replace it: this module for everything generic, plus a small **plugin** for what
is specific to the portal's LUCAS survey. The data migration itself is a script
that lives in the portal, not in this repository; this page says what maps to
what and what behaves differently.

## What moves where

| Portal | Here |
| --- | --- |
| Image collection | `images_collection`. `is_public` becomes `visibility = internal` (the portal's "public" always meant any signed-in user); a collection that should be anonymous becomes `public`, which needs `images.publish` |
| Collection roles view, contribute | A `view` or `edit` share (`/api/sharing/shares`, resource type `images.collection`) |
| Collection role manage | An `edit` share. Deleting images, editing the pipeline, whole-collection re-runs and prompt runs, and `auto_run` are the owner's or `images.manage`'s |
| Collection role own | `owner_id` |
| Image | `images_image`. Location precedence is `manual` (3) > `import` (2) > `exif` (1); store it as `location_source` |
| Five hardcoded pipeline status column pairs | `images_step_run` rows, one per `(image, step)`, with `status`, `step_version`, `error_code` and the step's `output` JSON (quality metrics, regions, labels) |
| Bag | `images_group` (`key`, `name`, `description`) plus `images_image.group_id` and `group_role`. The role order is `images_collection.group_roles` |
| Custom pipeline (instruction plus schema) | `images_prompt` (`scope` `image` or `group`), with results in `images_prompt_result` |
| AI results | The same rows, with review fields: `review_status` starts `unreviewed` |
| Import jobs and per-feature download rows | `images_import_job` and `images_import_item`; finished jobs are not worth migrating |
| `source_type`, `source_config` | Dropped. External connectors (Mapillary, Street View) had no code behind them |
| The `_LUCAS` preset, its vocabularies, prompts, schemas, cross-check, role order, filename pattern and the land-use prompt | A portal plugin, below. None of it is in this module |

Move the image objects into the module's key layout, or at least make sure every
row's `storage_key` names an object in the configured `file_storage` backend:

```
images/<tenant>/<collection>/<image>/original.<ext>
```

(`display.<generation>.<attempt>.jpg`, `r/<size>.<generation>.<attempt>.jpg` and
`map.<generation>.<attempt>.pmtiles` are produced by the module itself.) The
module has one layout where the portal had two. Let the pipeline regenerate
renditions rather than migrating thumbnails.

### Already-anonymised images

The portal's anonymisation **overwrote the original in place**, so a migrated
image has no unblurred copy. Keep its key as `storage_key` and leave `display_key`
empty: it is then served to everyone as its own original, with nothing to
restrict. This module has **no flag for "original not retained"**, so record that
in your migration if you need it (for example in `properties`). From now on, a
newly anonymised image keeps its original and gets a separate display copy; the
original is then served only to the owner and holders of `images.originals.view`.

### Billing

With `billing` installed, the `images.storage_bytes` gauge counts only the holds
images takes through its own ingest and pipeline. Images created by a data
migration have no hold (`storage_hold_id` is empty), so the gauge does not count
them until something changes their stored objects. If plan limits matter to you,
verify this on a copy before relying on it; it was not exercised.

## The plugin

Everything LUCAS becomes data plus a plugin ([writing-a-plugin.md](writing-a-plugin.md)):

```python
# lucas/images_extensions.py
from sm_images.contracts import Preset, PromptSpec


def register(registry) -> None:
    registry.register_preset(
        Preset(
            id="lucas",
            label_key="lucas.preset.label",
            pipeline={
                "anonymize": {"faces": True, "plates": True},
                "classify": {"vocabulary": LAND_USE_VOCABULARY, "instruction": LAND_USE_PROMPT},
            },
            group_roles=["point", "north", "east", "south", "west"],
            filename_patterns=[r"^(?P<group>.+?)LCLU_(?P<role>Point|North|South|East|West)"],
            prompts=[
                PromptSpec(
                    id="lucas.photo",
                    scope="image",
                    instruction=PHOTO_PROMPT,
                    output_schema=LUCAS_PHOTO_SCHEMA,
                    auto_run=True,
                ),
                PromptSpec(
                    id="lucas.summary",
                    scope="group",
                    inputs="results",
                    instruction=SUMMARY_PROMPT,
                    output_schema=LUCAS_SUMMARY_SCHEMA,
                ),
            ],
            cross_check=lucas_cross_check,
        )
    )
```

Its module declares `depends_on=["Images"]`, and its result views (the
cross-check, a prompt result) register from `images-steps.ts`. Keep the portal's
fixtures and views with the plugin. A custom `register_step` is needed only for
work a prompt cannot express.

## Behaviour that differs, deliberately

These are defects of the portal that the module does not carry over.

| Portal | Here |
| --- | --- |
| Anonymisation overwrites the original | The original is immutable; `anonymize` writes a display copy, and the original is a separate right |
| Deleting a collection removes only rows | Deleting trashes it; the janitor purges rows and objects after `janitor_grace_days` |
| The SSRF guard checks literals and a hostname blocklist | DNS is resolved, every address must be public, and the check repeats on each redirect |
| ZIP extraction has no limits | Size, entry-count, per-entry, total and ratio limits; zip-slip, symlinks, encrypted and nested archives refused |
| HEIC accepted but unreadable | `pillow-heif` is installed and HEIC works |
| A skipped step re-runs on retry; EXIF could overwrite API coordinates | `skipped` is final for a step version; a location never overrides a higher-precedence source |
| Thumbnails are one-hour presigned URLs | An access-checked route with ETags and long cache headers for public renditions; no URL expires while displayed |
| Downloads are re-encoded at 4000 px, quality 85 | Kept exactly as delivered; renditions cover display sizes |
| "Public" means any signed-in user; no admin bypass | `internal` for that; `public` is anonymous; `images.manage` bypasses |
| AI results are read-only | Accept, correct or reject, with the last five values kept |
| Shares have four roles | Two (view, edit); see the table above |
| Storage keys in two layouts | One |

The module also fixes things the portal never had: leases and fencing on every
step write, durable recovery of lost messages, a poison-job breaker for imports,
the original served only to those entitled to it, and gated lists, counts and
tiles so a caller never learns of an image they cannot open.

## Order of work

1. Install the module (and `ai`, `billing`, `quality` extras as needed), run the
   host migration for the images tables, and start the workers
   ([worker.md](worker.md)).
2. Install the LUCAS plugin in the web image **and** every worker image.
3. Run the portal's data migration, copying objects into the key layout.
4. Re-run the pipeline for the collections that need renditions or new steps
   (`POST /api/images/collections/{id}/pipeline/restart`, scope `all`).
5. Remove the portal's `features/images`.

Not verified: no production data was migrated, and the portal's tables were read
only through the design and porting notes, not executed against this module.
Rehearse step 3 on a copy.
