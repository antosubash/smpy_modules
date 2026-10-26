"""The bundle section's catalogue keys: spelled out, emitted, and translated (#80).

The vitest catalogue check counts a ``bundle.*`` key as used only when
``integrations/bundle/`` spells it out as a value. This holds those literals
to what the section actually hands pagebuilder — no dead constant can keep a
key alive — and to the catalogue, so no emitted key goes untranslated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import news
import pytest
from bundle_app import article, bundle_host, stage, take
from news.integrations.bundle import NewsBundleSection
from news.integrations.bundle.plan import LINE_KEYS

_ROOT = Path(news.__file__).parent
_LITERAL = re.compile(r'[=:]\s*"(news\.bundle\.[\w.]+)"')


def _spelled_out() -> set[str]:
    found: set[str] = set()
    for path in (_ROOT / "integrations" / "bundle").glob("*.py"):
        found.update(_LITERAL.findall(path.read_text()))
    return found


def _catalogue() -> set[str]:
    def walk(node: dict, prefix: str) -> set[str]:
        out: set[str] = set()
        for key, value in node.items():
            path = f"{prefix}.{key}"
            out |= walk(value, path) if isinstance(value, dict) else {path}
        return out

    en = json.loads((_ROOT / "locales" / "en.json").read_text())
    return walk(en["bundle"], "news.bundle")


def _declared() -> set[str]:
    section = NewsBundleSection()
    return {section.label_key, *section.count_label_keys.values(), *LINE_KEYS.values()}


def test_every_spelled_out_key_is_one_the_section_declares_and_the_catalogue_has():
    assert _spelled_out() == _declared() == _catalogue()


@pytest.mark.asyncio
async def test_a_plan_emits_every_line_key(tmp_path):
    """Every line is in every plan (an empty one shows a zero), so all are used."""
    async with bundle_host(tmp_path) as client:
        await article(client, "a")
        staged = await stage(client, (await take(client))["id"])

        [news_plan] = staged.json()["plan"]["sections"]
        assert {line["label_key"] for line in news_plan["lines"]} == set(LINE_KEYS.values())
