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

**The per-feature budget** (``geojson_max_feature_bytes``) counts the UTF-8
bytes of every key and string, plus a small constant per other scalar, for
container features and bare scalar features alike; a feature over it is never
built (``OVERSIZE``). Accepted residual: ijson hands over each *token* already
materialised, so one huge string is in memory before it can be counted - no
streaming JSON parser for Python bounds a single token. It is bounded by
``geojson_max_bytes``, the cap on the whole source.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO, Any, Final

import ijson

__all__ = [
    "OVERSIZE",
    "SKIP_TICK",
    "GeoJSONError",
    "Oversize",
    "Tick",
    "iter_features",
    "validate_and_count",
]

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


class Oversize:
    """Yielded in place of a feature over the byte budget; it was never built."""

    __slots__ = ()


OVERSIZE = Oversize()
_SCALAR_COST: Final = 8
_STARTS: Final = frozenset({"start_map", "start_array"})
_ENDS: Final = frozenset({"end_map", "end_array"})


def _cost(event: str, value: Any) -> int:
    """Bytes a token adds to its feature: UTF-8 length of keys and strings."""
    if event in ("string", "map_key"):
        return len(value.encode("utf-8", "surrogatepass"))
    return _SCALAR_COST


def iter_features(
    stream: IO[bytes], start: int = 0, max_feature_bytes: int | None = None
) -> Iterator[tuple[int, Any]]:
    """``(index, feature)`` for every feature from ``start`` on, by absolute
    index; a ``(index, Tick)`` every :data:`SKIP_TICK` features skipped before it.

    Features are built from ijson's event stream with a running byte budget
    (see the module docstring): once a feature passes ``max_feature_bytes`` its
    builder is dropped and ``(index, OVERSIZE)`` is yielded when it ends - the
    rest of the file streams on.
    A feature may be any JSON value - the caller decides what is usable."""
    stream.seek(0)
    index, depth, size = -1, 0, 0
    builder: ijson.ObjectBuilder | None = None
    try:
        for prefix, event, value in ijson.parse(stream, use_float=True):
            if depth == 0:
                if prefix != _ITEM or event not in _VALUE_EVENTS:
                    continue
                index += 1
                if index < start:
                    if index and index % SKIP_TICK == 0:
                        yield index, _TICK
                    if event in _STARTS:
                        depth, builder = 1, None
                    continue
                if event not in _STARTS:  # a bare scalar feature
                    over = max_feature_bytes is not None and _cost(event, value) > max_feature_bytes
                    yield index, (OVERSIZE if over else value)
                    continue
                depth, size, builder = 1, 0, ijson.ObjectBuilder()
                builder.event(event, value)
                continue
            if event in _STARTS:
                depth += 1
            elif event in _ENDS:
                depth -= 1
            if builder is not None:
                size += _cost(event, value)
                if max_feature_bytes is not None and size > max_feature_bytes:
                    builder = None  # stop building; the feature is reported as too large
                else:
                    builder.event(event, value)
            if depth == 0 and index >= start:
                yield index, (OVERSIZE if builder is None else builder.value)
                builder = None
    except ijson.JSONError as exc:
        raise GeoJSONError("invalid_json") from exc
