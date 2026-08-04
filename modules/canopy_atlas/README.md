# simple_module_canopy_atlas

The Global Canopy Atlas site as a SimpleModule add-on: its design pack, its
brand assets, and the seed that publishes its pages.

This module is the GCA *brand*. The widgets its pages are built from live in
`simple_module_pagebuilder`, where they are a generic section library — the
GCA-ness of them is entirely in the tokens this pack overrides.

## What it provides

- **A design pack.** `canopy_atlas/static/gca-pack.css`, scoped to `.gca-root`,
  overriding the base widget tokens with GCA's typography, neutrals and shape.
  The module registers it as `("gca", "Canopy Atlas")` so it appears in
  Settings → Branding. The *action* colour still comes from branding, not from
  the pack, so re-branding a deployment re-themes the site.
- **Brand assets.** Eight photographs, two logo lockups and seven partner marks,
  served from `/canopy-atlas/static/gca/`.
- **Seed content.** Twelve pages plus the site header and footer.

## Installation

```bash
pip install simple_module_canopy_atlas
```

A host picks the module up automatically via `entry_points`. Two things are not
automatic:

1. **The stylesheet.** The design-pack registry supplies the dropdown entry, not
   the CSS. Import the pack from the host's CSS entry point:

   ```css
   @import "@simple-module-py/canopy-atlas/canopy_atlas/static/gca-pack.css";
   ```

2. **The dependency on pagebuilder**, which the host must also install.

For an in-repo checkout, resolve it from the workspace:

```toml
dependencies = ["simple_module_canopy_atlas"]

[tool.uv.sources.simple_module_canopy_atlas]
workspace = true
```

## Usage

With the host running and migrated, publish the site:

```bash
uv run python -m canopy_atlas.seed
```

That uploads the photographs into pagebuilder's media library so an editor can
swap any of them from the image picker, rewrites the page content to point at
them, sets branding's app name, colour and design pack, and publishes the
twelve pages and the site layout.

Re-running is safe: uploads match on filename and pages on slug, so nothing
duplicates.

Options: `--base-url` (default `http://localhost:8000`), `--email`,
`--password`, and `--no-publish` to seed drafts instead of publishing.

The brand and partner marks stay on the static mount rather than the media
library, which rejects SVG because it can carry script and is served
same-origin.

## Development

```bash
uv sync --extra dev
uv run pytest
```

## API-version contract

`ModuleMeta.requires_framework` declares which `simple_module_core` versions
this module supports. Update the spec on each framework major bump after
verifying compatibility.
