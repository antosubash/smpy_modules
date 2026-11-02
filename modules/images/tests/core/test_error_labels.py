"""Every code a step, an import job or an item can end with has worded
``errors.*`` entries in both catalogues - the console shows the bare code
otherwise (``errorCodeLabel``) - and the wizard's input bounds match the
server's ``Mapping``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sm_images.core import constants
from sm_images.ingest.imports import access, recover, retrying
from sm_images.ingest.imports.features import PARSE_CODES
from sm_images.ingest.imports.filename_pattern import MAX_PATTERN_LENGTH
from sm_images.ingest.imports.mapping import Mapping, Prop
from sm_images.pipeline import plan
from sm_images.pipeline.ai.codes import AI_CODES
from sm_images.pipeline.reopen import PLACEHOLDER_CODES
from sm_images.web.endpoints.api.pipeline import CODE_INVALID_CONFIG

PKG = Path(constants.__file__).parent.parent  # sm_images/, above core/
CATALOGUES = ("en", "de")

EXECUTOR_CODES = frozenset(
    {
        "step_error",
        "invalid_output",
        "invalid_outcome",
        "invalid_config",
        "invalid_params",
        "time_limit",
        "internal_error",
        "not_applicable",  # a skip *reason*, never an error_code - worded anyway
    }
)
"""Literal codes of ``pipeline.executor`` and ``pipeline.config``."""

JOB_CODES = frozenset(
    {
        recover.STALLED,
        access.ACCESS_REVOKED,
        retrying.RETRY_AFTER_TOO_LONG,
        "dispatch_failed",
        "upload_expired",
        "seal_failed",
        "source_unreachable",
        "unsafe_source_url",
    }
)


def _raised_codes() -> set[str]:
    """Codes the import code raises as literals (archive and source refusals)."""
    found: set[str] = set()
    pattern = re.compile(r'(?:GeoJSONError|ZipRejected|FetchError)\("([a-z_]+)"')
    for path in (PKG / "ingest" / "imports").glob("*.py"):
        found.update(pattern.findall(path.read_text()))
    return found


def _every_code() -> set[str]:
    return {
        *plan.BLOCKED_CODES,
        plan.INVALID_PIPELINE,
        *PLACEHOLDER_CODES,
        *PARSE_CODES,
        *constants.ERROR_CODES,
        *AI_CODES,
        constants.TENANT_REQUIRED_CODE,
        constants.DIRECTORY_UNAVAILABLE_CODE,
        CODE_INVALID_CONFIG,
        *EXECUTOR_CODES,
        *JOB_CODES,
        *_raised_codes(),
    }


@pytest.mark.parametrize("lang", CATALOGUES)
def test_every_code_has_a_label(lang):
    errors = json.loads((PKG / "locales" / f"{lang}.json").read_text())["errors"]
    missing = sorted(c for c in _every_code() if not str(errors.get(c, "")).strip())
    assert missing == []


def test_the_wizard_bounds_match_the_mapping():
    (constraint,) = Prop.__metadata__
    props = [f for f in Mapping.model_fields if f.endswith("_prop")]
    assert {Mapping.model_fields[f].annotation for f in props} == {Prop | None}
    source = (PKG / "ui" / "components" / "imports" / "MappingFields.tsx").read_text()
    bounds = [int(n) for n in re.findall(r"maxLength=\{(\d+)\}", source)]
    assert bounds == [constraint.max_length, MAX_PATTERN_LENGTH]
