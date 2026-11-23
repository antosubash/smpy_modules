"""Packaging contract: the extras, their floors, and no exact pins (AGENTS.md pin policy)."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def test_extras_and_floors() -> None:
    extras = _project()["optional-dependencies"]
    assert extras["pagebuilder"] == ["simple_module_pagebuilder>=0.0.16,<0.1"]


def test_the_pagebuilder_floor_says_why() -> None:
    text = (ROOT / "pyproject.toml").read_text()
    assert re.search(r"# floor: 0\.0\.16.*pagebuilder-blocks\.ts", text, re.DOTALL)


def test_no_eq_pins() -> None:
    project = _project()
    requirements = list(project["dependencies"])
    for group in project["optional-dependencies"].values():
        requirements.extend(group)
    for requirement in requirements:
        assert not re.search(r"(?<![<>!~=])==", requirement), requirement


def test_pagebuilder_is_an_optional_peer_of_the_npm_package() -> None:
    manifest = json.loads((ROOT / "package.json").read_text())
    assert manifest["peerDependencies"]["@simple-module-py/pagebuilder"] == "*"
    assert manifest["peerDependencies"]["@puckeditor/core"].startswith("^0.24")
    assert manifest["peerDependenciesMeta"]["@simple-module-py/pagebuilder"] == {"optional": True}


def test_pagebuilder_is_a_workspace_source() -> None:
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    assert sources["simple_module_pagebuilder"] == {"workspace": True}
