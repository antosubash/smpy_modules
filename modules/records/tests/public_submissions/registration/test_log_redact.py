"""A confirm, unsubscribe or cancel link's token never reaches a log line."""

from __future__ import annotations

import logging

import pytest
from sm_records.core import constants, log_redact

TOKEN = "eyJ0IjoiY29uZmlybSJ9.abcdefghijklmnopqrstuvwxyz0123456789"


def test_the_token_query_of_every_landing_page_is_redacted():
    """Over the real route list: every page of the landing router is covered, so a new token page
    fails here until it is redacted."""
    from sm_records.web.endpoints.public_submissions_views import router

    pages = sorted(
        constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX + route.path.lstrip("/")
        for route in router.routes
        if getattr(route, "path", "")
    )
    assert {p.rsplit("/", 1)[1] for p in pages} >= {"confirm", "confirm-registration", "cancel"}
    for path in pages:
        line = f'127.0.0.1:1234 - "GET {path}?t={TOKEN}&l=de HTTP/1.1" 200'
        cleaned = log_redact.redact(line)
        assert TOKEN not in cleaned and "t=<redacted>" in cleaned and "&l=de" in cleaned, path


@pytest.mark.parametrize("name", ["uvicorn.access", "simple_module.request", "uvicorn.error"])
def test_the_filter_covers_the_access_and_request_logs(caplog, name):
    log_redact.install()
    logger = logging.getLogger(name)
    with caplog.at_level(logging.INFO, logger=name):
        logger.info(
            '%s - "GET %s HTTP/%s" %d',
            "1.2.3.4",
            f"/records/submissions/cancel?t={TOKEN}",
            "1.1",
            200,
        )
        logger.info("request", extra={"path": f"/records/submissions/confirm?t={TOKEN}"})
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in str(record.__dict__.get("path", ""))


def test_install_is_idempotent_and_leaves_other_text_alone():
    log_redact.install()
    log_redact.install()
    assert (
        sum(isinstance(f, log_redact.Filter) for f in logging.getLogger("uvicorn.access").filters)
        == 1
    )
    assert log_redact.redact("GET /records/x?page=2&t2=ok") == "GET /records/x?page=2&t2=ok"
