"""The scripted aiosmtpd relay, for the test send's SMTP path."""

from tests.sending.conftest import (  # noqa: F401 - re-exported fixtures
    client_tls,
    make_transport,
    relay,
    tls_files,
)
