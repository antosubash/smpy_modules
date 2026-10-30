"""The pure half of GeoJSON imports: validation, streaming, feature extraction,
filename patterns (ports of the portal's ``test_geojson_robustness`` and
``test_regex_safety`` cases, plus the porting map's static findings 1, 4 and 5)."""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import UTC, datetime

import pytest
from sm_images.imports.features import base64_external_id, extract, url_external_id
from sm_images.imports.filename_pattern import PatternError, compile_pattern, match_group
from sm_images.imports.geojson_stream import GeoJSONError, Tick, iter_features, validate_and_count
from sm_images.imports.mapping import Mapping, MappingError
from sm_images.models.enums import ImportKind

URL = ImportKind.GEOJSON_URL
B64 = ImportKind.GEOJSON_BASE64
JOB = uuid.UUID(int=7)


def doc(features, **root) -> io.BytesIO:
    return io.BytesIO(
        json.dumps({"type": "FeatureCollection", "features": features, **root}).encode()
    )


def feat(props=None, geometry=None):
    return {"type": "Feature", "properties": props, "geometry": geometry}


def test_count_and_stream_by_absolute_index():
    src = doc([feat({"u": f"http://x/{i}.jpg"}) for i in range(5)])
    assert validate_and_count(src, 10) == 5
    got = [(i, f["properties"]["u"]) for i, f in iter_features(src, start=3)]
    assert got == [(3, "http://x/3.jpg"), (4, "http://x/4.jpg")]


def test_root_type_after_features_is_valid():
    """Static finding 1: JSON key order is irrelevant."""
    src = io.BytesIO(b'{"features": [{"type": "Feature"}], "type": "FeatureCollection"}')
    assert validate_and_count(src, 10) == 1


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"type": "FeatureCollection", "features": [{"a": 1}, {"b"', "invalid_json"),
        (b'{"type": "Feature", "features": []}', "not_feature_collection"),
        (b'[{"type": "FeatureCollection"}]', "not_feature_collection"),
        (b'{"type": "FeatureCollection"}', "missing_features"),
        (b'{"type": "FeatureCollection", "features": {}}', "missing_features"),
    ],
)
def test_unusable_documents_are_refused(raw, code):
    with pytest.raises(GeoJSONError) as err:
        validate_and_count(io.BytesIO(raw), 10)
    assert err.value.code == code


def test_feature_limit():
    with pytest.raises(GeoJSONError) as err:
        validate_and_count(doc([feat() for _ in range(4)]), 3)
    assert err.value.code == "too_many_features"
    assert validate_and_count(doc([feat() for _ in range(3)]), 3) == 3


def test_skipping_to_a_resume_point_ticks(monkeypatch):
    from sm_images.imports import geojson_stream

    monkeypatch.setattr(geojson_stream, "SKIP_TICK", 2)
    src = doc([feat() for _ in range(6)])
    seen = [(i, isinstance(f, Tick)) for i, f in iter_features(src, start=5)]
    assert seen == [(2, True), (4, True), (5, False)]


def test_null_properties_and_non_dict_features_do_not_crash():
    m = Mapping(url_prop="url")
    assert extract(feat(None), 0, kind=URL, mapping=m, job_id=JOB).error == "missing_url"
    for bad in ("text", 3, None, [1, 2]):
        assert extract(bad, 1, kind=URL, mapping=m, job_id=JOB).error == "invalid_feature"


def test_ijson_numbers_are_floats_so_polygon_and_timestamps_work():
    ring = [[10.0, 50.0], [12.0, 50.0], [12.0, 52.0], [10.0, 52.0], [10.0, 50.0]]
    src = doc(
        [
            feat(
                {"url": "https://h/a.jpg", "t": 1_700_000_000},
                {"type": "Polygon", "coordinates": [ring]},
            )
        ]
    )
    validate_and_count(src, 5)
    ((_, feature),) = list(iter_features(src))
    p = extract(
        feature, 0, kind=URL, mapping=Mapping(url_prop="url", datetime_prop="t"), job_id=JOB
    )
    assert (p.lat, p.lng) == (51.0, 11.0)
    assert p.captured_at == datetime.fromtimestamp(1_700_000_000, UTC)
    json.dumps(p.properties)  # retained properties are plain JSON


def test_coordinates_are_validated_and_zero_is_a_location():
    m = Mapping(url_prop="url", lat_prop="lat", lng_prop="lng")
    base = {"url": "https://h/a.jpg"}
    assert extract(feat({**base, "lat": 0, "lng": 0}), 0, kind=URL, mapping=m, job_id=JOB).lat == 0
    for lat, lng in ((91, 0), (0, 181), ("nan", 1), (True, 1)):
        p = extract(feat({**base, "lat": lat, "lng": lng}), 0, kind=URL, mapping=m, job_id=JOB)
        assert (p.lat, p.lng) == (None, None)
    point = {"type": "Point", "coordinates": [8.5, 47.3]}
    p = extract(feat({**base, "lat": "x"}, point), 0, kind=URL, mapping=m, job_id=JOB)
    assert (p.lat, p.lng) == (47.3, 8.5)  # falls back to the geometry


def test_external_id_defaults():
    url = "https://h/p/a%20b.jpg?x=1"
    p = extract(feat({"url": url}), 4, kind=URL, mapping=Mapping(url_prop="url"), job_id=JOB)
    assert p.external_id == url_external_id(url) and len(p.external_id) == 32
    assert p.filename == "a b.jpg"
    m = Mapping(image_prop="img", external_id_prop="id")
    p = extract(feat({"img": "AAAA", "id": 12}), 4, kind=B64, mapping=m, job_id=JOB)
    assert (p.external_id, p.payload, p.properties) == ("12", "AAAA", {"id": 12})
    p = extract(feat({"img": "AAAA"}), 4, kind=B64, mapping=m, job_id=JOB)
    assert p.external_id == base64_external_id(JOB, 4)
    assert p.properties is None  # the image itself is never retained


def test_url_must_be_http():
    m = Mapping(url_prop="url")
    for bad in ("ftp://h/a.jpg", "file:///etc/passwd", "h/a.jpg", "https://h/" + "a" * 2000):
        assert (
            extract(feat({"url": bad}), 0, kind=URL, mapping=m, job_id=JOB).error == "invalid_url"
        )


def test_property_groups_keep_zero_and_roles_follow_the_collection():
    m = Mapping(url_prop="url", group_key_prop="site", group_role_prop="dir")
    roles = ["point", "North"]
    f = feat({"url": "https://h/a.jpg", "site": 0, "dir": "NORTH"})
    p = extract(f, 0, kind=URL, mapping=m, job_id=JOB, roles=roles)
    assert (p.group_key, p.group_role) == ("0", "North")
    f = feat({"url": "https://h/a.jpg", "site": " P1 ", "dir": "diagonal"})
    p = extract(f, 0, kind=URL, mapping=m, job_id=JOB, roles=roles)
    assert (p.group_key, p.group_role) == ("P1", None)


def test_filename_pattern_groups():
    pattern = r"^(?P<group>[A-Z]+\d+)_(?P<role>[a-z]+)"
    roles = ["point", "north"]
    assert match_group(pattern, "AB12_north.jpg", roles) == ("AB12", "north")
    assert match_group(pattern, "ab12_Point.jpg", roles) == ("ab12", "point")
    assert match_group(pattern, "AB12_up.jpg", roles) == ("AB12", None)
    assert match_group(pattern, "nothing.jpg", roles) == (None, None)
    m = Mapping(url_prop="url", filename_pattern=pattern)
    p = extract(
        feat({"url": "https://h/x/C3_north.jpg"}), 0, kind=URL, mapping=m, job_id=JOB, roles=roles
    )
    assert (p.group_key, p.group_role) == ("C3", "north")


def test_a_catastrophic_pattern_returns_within_the_timeout():
    started = time.monotonic()
    assert match_group(r"^(?P<group>(a+)+)$", "a" * 40 + "!", []) == (None, None)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("bad", ["(?P<group>", "no-group-here", "x" * 600])
def test_bad_patterns_are_refused(bad):
    with pytest.raises((PatternError, ValueError)):
        compile_pattern(bad)
    with pytest.raises(ValueError):
        Mapping(url_prop="u", filename_pattern=bad)


def test_mapping_must_name_the_source_property():
    with pytest.raises(MappingError, match="url_prop_required"):
        Mapping(image_prop="i").require(URL)
    with pytest.raises(MappingError, match="image_prop_required"):
        Mapping(url_prop="u").require(B64)
    with pytest.raises(MappingError, match="unsupported_kind"):
        Mapping(url_prop="u").require(ImportKind.ZIP)
