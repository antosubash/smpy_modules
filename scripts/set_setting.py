#!/usr/bin/env python
"""Write a module setting into the database, without the admin UI.

Module settings live in the settings module's SYSTEM-scoped store and are
normally edited on the Settings screen. That is no help to anything headless —
a fresh deployment, a CI job, the e2e stack — which needs the site configured
*before* anyone can log in and configure it.

    python scripts/set_setting.py pagebuilder content_locales '["en","de"]'
    python scripts/set_setting.py pagebuilder default_content_locale en
    python scripts/set_setting.py news public_route_prefix /blog

The value is written in whatever encoding the field's declared type calls for
(``json`` for containers, otherwise the raw string), read back by the
hydrator at the next boot, and validated by pydantic then — so a typo here
surfaces as a startup error naming the field rather than a silently ignored
line, which is what the environment variables this replaced used to do.

The app is constructed (not started) purely to collect the registry every
module fills in during ``register_settings``: that is what knows which fields
a package has and how each is typed, so this script needs no list of its own.
"""

from __future__ import annotations

import asyncio
import json
import sys

from settings.hydrate import value_type_for_field
from settings.service import SettingService
from settings.store import SettingsStore
from simple_module_hosting.app_builder import create_app
from simple_module_hosting.settings import Settings

_USAGE = "usage: set_setting.py <package> <field> <value> [<field> <value> ...]"


async def _write(package: str, pairs: list[tuple[str, str]]) -> None:
    app = create_app(Settings())
    registry = app.state.settings.module_registry
    cls = registry.get(package)
    if cls is None:
        known = ", ".join(registry.all_packages())
        raise SystemExit(f"unknown package {package!r}; registered: {known}")

    async with app.state.sm.db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        for field, raw in pairs:
            if field not in cls.model_fields:
                fields = ", ".join(sorted(cls.model_fields))
                raise SystemExit(f"{package} has no field {field!r}; try: {fields}")
            value_type = value_type_for_field(cls, field)
            if value_type == "json":
                # Fail here rather than at the next boot: a malformed value
                # written now is a startup crash later, at a distance from the
                # command that caused it. Optional strings land in this branch
                # too — the store types anything that isn't a plain str/int/
                # bool/float as JSON — so say what the quoted form looks like
                # rather than only that the parse failed.
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise SystemExit(
                        f"{package}.{field} is stored as JSON and {raw!r} is not "
                        f'valid JSON ({exc}). A string value is quoted: \'"{raw}"\''
                    ) from exc
            await store.set_override(package, field, raw, value_type)
            print(f"{package}.{field} = {raw} ({value_type})")
        await session.commit()
    await app.state.sm.db.engine.dispose()


def main(argv: list[str]) -> int:
    if len(argv) < 3 or len(argv) % 2 == 0:
        print(_USAGE, file=sys.stderr)
        return 2
    package, rest = argv[0], argv[1:]
    pairs = list(zip(rest[::2], rest[1::2], strict=True))
    asyncio.run(_write(package, pairs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
