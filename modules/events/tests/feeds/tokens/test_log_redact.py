"""The token never reaches a log line: not the request log, the rate limiter or uvicorn."""

from __future__ import annotations

import io
import logging

import pytest
from sm_events.feeds.tokens import log_redact
from sm_events.feeds.tokens.codec import new_token

TOKEN = "evf_" + "A" * 43


def _record(msg, args=(), **extra) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_filter_rewrites_msg_args_and_path_extra():
    record = _record(
        "%s %s",
        ("GET", "/events/feed/evf_abc.ics"),
        path="/de/events/feed/evf_abc.ics?x=1",
    )
    assert log_redact.Filter().filter(record) is True
    assert record.getMessage() == "GET /events/feed/<redacted>"
    assert record.path == "/de/events/feed/<redacted>?x=1"  # type: ignore[attr-defined]


def test_filter_rewrites_a_dict_of_args_and_the_message():
    record = _record("GET /events/feed/evf_abc.ics %(code)s", ({"code": 200},))
    log_redact.Filter().filter(record)
    assert record.getMessage() == "GET /events/feed/<redacted> 200"


def test_other_paths_are_untouched():
    record = _record("%s", ("/events/feedback",), path="/events/feed", note="/events/c/feed")
    log_redact.Filter().filter(record)
    assert record.getMessage() == "/events/feedback"
    assert record.path == "/events/feed"  # type: ignore[attr-defined]
    assert record.note == "/events/c/feed"  # type: ignore[attr-defined]


def test_a_token_is_scrubbed_wherever_it_appears():
    """A token in an exception's text or a free-form message, off the ``/feed/`` path."""
    record = _record("bad link %s", (ValueError(f"nope {TOKEN}"),), note=f"x {TOKEN} y")
    log_redact.Filter().filter(record)
    assert TOKEN not in record.getMessage()
    assert TOKEN not in str(record.__dict__)


def test_a_traceback_is_scrubbed():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("events.test.traceback")
    logger.propagate = False
    logger.addHandler(handler)
    logger.addFilter(log_redact.Filter())
    try:
        raise ValueError(f"GET /events/feed/{TOKEN}.ics failed")
    except ValueError:
        logger.exception("boom")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "ValueError" in out
    assert TOKEN not in out
    assert "/events/feed/<redacted>" in out


def test_a_fresh_token_never_survives():
    token = new_token()
    record = _record("%s", (f"/events/feed/{token}.ics",), path=f"/events/feed/{token}.ics")
    log_redact.Filter().filter(record)
    assert token not in str(record.__dict__) and token not in record.getMessage()


def test_install_idempotent_on_each_logger():
    for _ in range(3):
        log_redact.install()
    for name in log_redact.LOGGERS:
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, log_redact.Filter)]
        assert len(filters) == 1, name


def test_rate_limit_logger_name_exists():
    from simple_module_hosting import _observability, _rate_limit

    assert _rate_limit.logger.name in log_redact.LOGGERS
    assert _observability._request_logger.name in log_redact.LOGGERS
    assert "uvicorn.access" in log_redact.LOGGERS


@pytest.mark.parametrize("name", log_redact.LOGGERS)
def test_installed_filter_reaches_a_record_logged_on_the_logger(name, caplog):
    log_redact.install()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger(name).warning("hit /events/feed/%s.ics", TOKEN)
    assert TOKEN not in caplog.text


def test_a_digest_is_scrubbed():
    """What the lookup binds is logged by database drivers at DEBUG: never the digest either."""
    from sm_events.feeds.tokens.codec import hash_token

    digest = hash_token(TOKEN)
    record = _record("SELECT ... WHERE token_hash = ?", (), params=(digest,), note=f"x{digest}y")
    record.name = "sqlalchemy.engine.Engine"
    record.msg = f"executing {record.msg!r} with {(digest,)!r}"
    log_redact.Filter().filter(record)
    assert digest not in record.getMessage() and digest not in str(record.__dict__)
    keep = "a" * 63  # not a digest
    assert log_redact.redact(keep) == keep


@pytest.fixture
def root_handler():
    """A handler on the root logger, as an operator's logging setup installs one."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.DEBUG)
    yield handler, stream
    root.removeHandler(handler)
    root.setLevel(old)


@pytest.mark.parametrize(
    "name",
    ["some.unrelated.child", "uvicorn.asgi", "gunicorn.access", "sqlalchemy.engine.Engine.x"],
)
def test_handlers_redact_records_of_any_logger(root_handler, name):
    """A logger's own filter sees only its own records; a handler's sees every record that
    reaches it, whichever logger made it (``uvicorn.asgi``, gunicorn, a child logger)."""
    _handler, stream = root_handler
    log_redact.install()
    logging.getLogger(name).warning("GET /events/feed/%s.ics", TOKEN)
    logging.getLogger(name).warning("scope %r", {"path": f"/de/events/feed/{TOKEN}.ics"})
    assert TOKEN not in stream.getvalue()
    assert "<redacted>" in stream.getvalue()


def test_install_is_idempotent_on_handlers(root_handler):
    handler, _stream = root_handler
    for _ in range(3):
        log_redact.install()
    assert len([f for f in handler.filters if isinstance(f, log_redact.Filter)]) == 1


def test_a_handler_added_after_install_is_covered_by_the_next_install(root_handler):
    """The stated limit: a handler an operator adds *after* startup is not covered until
    ``install`` runs again (it is cheap and idempotent), and proxies log on their own."""
    log_redact.install()
    late = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(late)
    try:
        assert not any(isinstance(f, log_redact.Filter) for f in late.filters)
        log_redact.install()
        assert any(isinstance(f, log_redact.Filter) for f in late.filters)
    finally:
        logging.getLogger().removeHandler(late)


def test_another_modules_checksum_is_left_alone():
    """The digest scrub is for the database loggers: a 64-hex checksum elsewhere is not ours."""
    checksum = "ab" * 32
    record = _record("artifact sha256=%s", (checksum,))
    record.name = "some_module.images"
    log_redact.Filter().filter(record)
    assert checksum in record.getMessage()
    leaked = _record("GET /events/feed/%s.ics", (checksum,))
    leaked.name = "some_module.images"
    log_redact.Filter().filter(leaked)
    assert checksum not in leaked.getMessage()  # a path after /feed/ is still redacted
