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

A ``json`` field is stored as its type *dumps* it, as the Settings screen
stores it (framework GH #487): the value is validated against the field's own
annotation and that dump is written. That is what keeps a sealed secret sealed
here too — records' CAPTCHA secret (#350) dumps as ``enc:v2:…``, so it is never
stored in the clear. A value the settings screen would mask is not echoed.

The app is constructed (not started) purely to collect the registry every
module fills in during ``register_settings``: that is what knows which fields
a package has and how each is typed, so this script needs no list of its own.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Any

from headless_settings import headless_settings
from pydantic import TypeAdapter, ValidationError
from settings.core.service import SettingService
from settings.module_settings.store import SettingsStore
from simple_module_core.secret_fields import conceals_secret
from simple_module_core.settings_hydrate import value_type_for_field
from simple_module_hosting.app_builder import create_app

_USAGE = "usage: set_setting.py <package> <field> <value> [<field> <value> ...]"


def _stored_json(cls: Any, package: str, field: str, raw: str) -> str:
    """``raw`` as the field's annotation validates and dumps it, as JSON text."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Fail here rather than at the next boot: a malformed value written now
        # is a startup crash later, at a distance from the command that caused
        # it. Optional strings land here too — the store types anything that
        # isn't a plain str/int/bool/float as JSON — so say what the quoted
        # form looks like rather than only that the parse failed.
        raise SystemExit(
            f"{package}.{field} is stored as JSON and the value is not valid JSON "
            f"({exc.msg}). A string value is quoted: '\"<value>\"'"
        ) from None
    info = cls.model_fields[field]
    annotation = Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    adapter: TypeAdapter[Any] = TypeAdapter(annotation)
    try:
        value = adapter.validate_python(parsed)
    except ValidationError as exc:
        # The messages only: an error's ``input`` would echo the value.
        reasons = "; ".join(error["msg"] for error in exc.errors(include_input=False))
        raise SystemExit(f"{package}.{field}: {reasons}") from None
    return json.dumps(adapter.dump_python(value, mode="json"))


async def _write(package: str, pairs: list[tuple[str, str]]) -> None:
    app = create_app(headless_settings())
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
            stored = _stored_json(cls, package, field, raw) if value_type == "json" else raw
            await store.set_override(package, field, stored, value_type)
            shown = "<hidden>" if conceals_secret(field, raw, value_type) else stored
            print(f"{package}.{field} = {shown} ({value_type})")
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
