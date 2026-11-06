"""Packaging contract: extras, floors and no exact pins (CLAUDE.md pin policy)."""

import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _project() -> dict:
    return tomllib.loads(_PYPROJECT.read_text())["project"]


def test_extras_and_floors() -> None:
    project = _project()
    extras = project["optional-dependencies"]
    assert extras["news"] == ["simple_module_news>=0.0.13,<0.1"]
    assert extras["pagebuilder"] == ["simple_module_pagebuilder>=0.0.13,<0.1"]
    assert "aiosmtplib>=3.0,<6" in project["dependencies"]
    assert "email-validator>=2.1" in project["dependencies"]
    assert "aiosmtpd>=1.4.6" in extras["dev"]


def test_no_eq_pins() -> None:
    project = _project()
    requirements = list(project["dependencies"])
    for group in project["optional-dependencies"].values():
        requirements.extend(group)
    for requirement in requirements:
        assert not re.search(r"(?<![<>!~=])==", requirement), requirement
