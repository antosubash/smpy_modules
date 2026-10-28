"""Streaming a GeoJSON FeatureCollection with ijson, one feature at a time.

Ported from the portal's ``geojson_stream.py``, with its key-order bug fixed
(static finding 1): the portal stopped at ``features`` and then reported a
``type`` that came *after* it as missing. :func:`validate_and_count` reads the
whole document once instead - which it must anyway, because a complete count is
what catches a truncated body - and checks the root's ``type`` wherever it is.

``use_float=True`` everywhere: ijson otherwise yields ``Decimal``, which breaks
coordinate arithmetic, timestamps and the JSON the retained properties are
stored as.

Both functions take a seekable binary file (a spool) and leave it at offset 0.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO, Any, Final

import ijson

__all__ = ["SKIP_TICK", "GeoJSONError", "Tick", "iter_features", "validate_and_count"]

SKIP_TICK: Final = 10_000
"""While skipping to a resume point, yield a :class:`Tick` this often, so the
runner can heartbeat through a long replay that produces nothing."""

_ITEM: Final = "features.item"
_VALUE_EVENTS: Final = frozenset(
    {"start_map", "start_array", "string", "number", "boolean", "null"}
)


class GeoJSONError(Exception):
    """The document is unusable: never retried. ``code`` is a constant."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Tick:
    """A placeholder yielded while skipping; carries no feature."""

    __slots__ = ()


_TICK = Tick()


def validate_and_count(stream: IO[bytes], max_features: int) -> int:
    """The number of features, after checking the document is a complete
    FeatureCollection with a ``features`` array.

    Raises :class:`GeoJSONError` - ``invalid_json`` (including a truncated
    body), ``not_feature_collection``, ``missing_features`` or
    ``too_many_features`` (as soon as the count passes ``max_features``).
    """
    stream.seek(0)
    root_type: Any = None
    has_features = False
    count = 0
    try:
        events = ijson.parse(stream, use_float=True)
        first = next(events, None)
        if first is None or first[:2] != ("", "start_map"):
            raise GeoJSONError("not_feature_collection")
        for prefix, event, value in events:
            if prefix == _ITEM and event in _VALUE_EVENTS:
                count += 1
                if count > max_features:
                    raise GeoJSONError("too_many_features")
            elif prefix == "type" and event in _VALUE_EVENTS:
                root_type = value
            elif prefix == "features" and event in _VALUE_EVENTS:
                if event != "start_array":
                    raise GeoJSONError("missing_features")
                has_features = True
    except ijson.JSONError as exc:
        raise GeoJSONError("invalid_json") from exc
    finally:
        stream.seek(0)
    if root_type != "FeatureCollection":
        raise GeoJSONError("not_feature_collection")
    if not has_features:
        raise GeoJSONError("missing_features")
    return count


def iter_features(stream: IO[bytes], start: int = 0) -> Iterator[tuple[int, Any]]:
    """``(index, feature)`` for every feature from ``start`` on, by absolute
    index; a ``(index, Tick)`` every :data:`SKIP_TICK` features skipped before
    it. A feature may be any JSON value - the caller decides what is usable."""
    stream.seek(0)
    try:
        for index, feature in enumerate(ijson.items(stream, _ITEM, use_float=True)):
            if index < start:
                if index and index % SKIP_TICK == 0:
                    yield index, _TICK
                continue
            yield index, feature
    except ijson.JSONError as exc:
        raise GeoJSONError("invalid_json") from exc
