# CLAUDE.md

Guidance for Claude Code in this repository. See `README.md` for general
project documentation.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`. `host/` is a
development app that mounts them; it is never published.

## Rules that are easy to get wrong

**Pin policy differs by role.** Published modules depend on the framework with
*ranges* (`simple_module_core>=0.0.25,<0.1`). The host pins *exactly*
(`simple_module_hosting==0.0.25`). Never give a published module an `==` pin —
it becomes uninstallable in any host running a newer framework build.

**Migrations live in `host/migrations/versions/`, never in a module.** Modules
ship SQLModel tables; each consuming host autogenerates its own revisions
against them. A module's first revision carries
`branch_labels = ("<module>",)` so the revision can be named
(`alembic downgrade <module>@base`). **That does not roll back only that
module.** Autogenerate chains every revision off the current head, so the
labelled revision sits on one linear history and `<module>@base` walks
everything beneath it — verified: `downgrade records@base` ran 20 downgrades
and emptied the database. Removing one module's schema in isolation needs its
tables on a real branch (`down_revision = None`), which nothing here produces
yet. Upstream: antosubash/simple_module_python#333.

**A page's language is fixed for its lifetime.** Slugs are unique per
`(locale, slug)`, and a rename records a redirect scoped to that locale.
Moving a page between languages would strand its slug in the old one and
orphan the redirect pointing at it, so there is no "change language" — there
is `POST /pages/{id}/translations`, which creates a sibling sharing a
`translation_group`. Every slug lookup, redirect and public claim takes a
locale; adding one that does not is how `/de/p/x` starts serving the English
page.

**Never add a file under `modules/*/*/pages/` unless it is a real Inertia
page.** The page name is derived from that path by `import.meta.glob`, so a
stray `.tsx` there silently registers a new page. Extractions go to
`components/`, `hooks/`, or `utils/`.

**Releases are lockstep.** One version across the repo. `scripts/bump_version.py`
is the only thing that edits versions, and it must never rewrite framework
dependency specifiers — the framework's own copy of that script does, which
would pin the framework to a version that doesn't exist. `scripts/tests/`
guards this and CI runs `--check-current`.

**`pagebuilder` and `news` read no environment variables.** Their settings are
DB-backed through the framework's settings module (`register_module_settings`),
and both classes drop pydantic-settings' env, `.env` and secrets sources — so
adding a field means adding it to the class, not to `.env.example`, and an
`SM_PAGEBUILDER_*` line anywhere is dead. Configure them on the Settings screen
or with `scripts/set_setting.py`. Anything the module reads while booting
(route prefixes, `content_locales`, the media mount) has to be read from
`app.state.<package>.settings` in `on_startup`, not during app construction:
hydration happens at lifespan start, so a value read earlier is the pydantic
default no matter what the database says. Mark such fields
`json_schema_extra=_RESTART` so the Settings screen says a restart is needed.

**Run Python entry points from the repo root.** `alembic.ini` resolves its
`script_location` relative to itself and `dev-api` uses `--app-dir host`, so
the root `.env` is the single source of truth for settings regardless of the
command.

**300-line cap** on every `.py` / `.ts` / `.tsx`, enforced by
`scripts/check_file_size.py`. Nothing under `modules/` is exempt.

## Local database (shared dev-services stack)

**Do NOT spin up a new Postgres container for local dev.** All repos under
`/Volumes/ext1/GitHub` share one stack defined in
`/Volumes/ext1/GitHub/dev-services` (PostGIS + Redis + MinIO + Adminer on the
`devnet` Docker network). Start it once with `make up` there.

Local dev defaults to **SQLite** (`host/app.db`), so Postgres is optional. To
use it, set:

```
SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules
```

Add the database to `dev-services/init/01-databases.sql` if it doesn't exist.
If 5432 is taken by an old per-project container, stop that container rather
than remapping ports. This repo does not use Redis or Celery.

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
make unlink-framework
```

Editable-installs the framework's `core`/`db`/`hosting` into the workspace
venv and back. Neither touches a tracked file.

## Known deferred work

- **UI i18n.** No module here is translated — pagebuilder, news and
  canopy_atlas all have hardcoded English TSX and no `locales/en.json`. The
  framework's own modules do have one, and the convention depends on
  `@simple-module-py/i18n` (`t(keys.<module>.<section>.<key>)`). The host
  *does* now wire it (`host/client_app/app.tsx` configures the catalog from
  the `i18n` shared prop, and the framework mounts `LocaleMiddleware`), so the
  blocker is gone — what remains is the conversion itself, and all three
  modules should convert together rather than piecemeal during unrelated work.

  Not to be confused with **content** i18n, which is done: pages and articles
  can be published in several languages. That is pagebuilder's
  `content_locales` setting and `pagebuilder.locales`, deliberately separate
  from the host's `SM_I18N_SUPPORTED_LOCALES` above — one decides what the site
  publishes, the other what the console speaks.
- **`smpy_pagebuilder`** still holds the pre-port copy of this module. This
  repo is canonical; that one is frozen.
