"""Why a fetch failed, as constant codes safe to store and show."""

from __future__ import annotations

__all__ = ["FetchError", "FetchTimeoutError", "FetchTooLargeError"]


class FetchError(Exception):
    """A fetch that failed for a reason worth recording. ``code`` is a constant."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FetchTooLargeError(FetchError):
    """The body is (declared or actually) larger than ``max_bytes``. Permanent."""

    def __init__(self) -> None:
        super().__init__("too_large")


class FetchTimeoutError(FetchError):
    """The whole fetch overran its wall-clock budget (a trickling body). Retryable."""

    def __init__(self) -> None:
        super().__init__("timeout")
