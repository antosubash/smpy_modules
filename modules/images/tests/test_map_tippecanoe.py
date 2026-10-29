"""tippecanoe itself (Task 26): the portal's arguments, the NDJSON, the real run.

``test_tiles_have_no_filenames`` builds a real archive and reads every tile
back: nothing of an image but its id, capture time and group reaches the map.
Skipped where tippecanoe is not installed (CI installs it).
"""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import UTC, datetime

import pytest
from sm_images.map import build, pmtiles_build
from sm_images.models import Image
from sqlalchemy import update

from tests.test_map_build import T, _located, _request, _state

# --- tippecanoe ---------------------------------------------------------------


def test_tippecanoe_args_are_the_portals(monkeypatch, tmp_path):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return

    monkeypatch.setattr(pmtiles_build.subprocess, "run", run)
    src, out = tmp_path / "in.ndjson", tmp_path / "out.pmtiles"
    src.write_text("{}\n")
    pmtiles_build.convert("/opt/tippecanoe", src, out, 10)
    assert seen["cmd"] == [
        "/opt/tippecanoe",
        "-o",
        str(out),
        "-Z",
        "0",
        "-z",
        "14",
        "-l",
        "images",
        "--force",
        "-r1",
        "--cluster-distance=10",
        "--cluster-maxzoom=13",
        "--cluster-densest-as-needed",
        "--drop-fraction-as-needed",
        str(src),
    ]
    assert seen["kw"]["timeout"] == 120
    assert seen["kw"].get("shell", False) is False
    assert seen["kw"]["check"] is True
    pmtiles_build.convert("/opt/tippecanoe", src, out, 100_000)
    assert "--read-parallel" in seen["cmd"] and seen["cmd"][-1] == str(src)
    assert seen["kw"]["timeout"] == 120 + 10 * 30
    assert pmtiles_build.timeout_for(5_000_000) == 3600


def test_ndjson_holds_only_id_captured_at_and_group(tmp_path):
    when = datetime(2026, 1, 2, tzinfo=UTC)
    gid = uuid.uuid4()
    rows = [
        (uuid.uuid4(), 48.2, 16.37, when, gid),
        (uuid.uuid4(), 95.0, 0.0, None, None),  # out of range: skipped
        (uuid.uuid4(), float("nan"), 0.0, None, None),
    ]
    path = tmp_path / "p.ndjson"
    with path.open("w", encoding="utf-8") as fh:
        assert pmtiles_build.write_features(fh, rows) == 1
    (line,) = path.read_text().splitlines()
    feature = json.loads(line)
    assert feature["geometry"] == {"type": "Point", "coordinates": [16.37, 48.2]}
    assert feature["properties"] == {
        "id": str(rows[0][0]),
        "captured_at": when.isoformat(),
        "group_id": str(gid),
    }


def test_locate(tmp_path):
    assert pmtiles_build.locate(str(tmp_path / "missing")) is None
    assert pmtiles_build.locate("definitely-not-a-binary-xyz") is None


def _tile_bytes(data: bytes) -> list[bytes]:
    from pmtiles.reader import MemorySource, all_tiles

    out = []
    for _, tile in all_tiles(MemorySource(data)):
        out.append(gzip.decompress(tile) if tile[:2] == b"\x1f\x8b" else tile)
    return out


@pytest.mark.skipif(pmtiles_build.locate("tippecanoe") is None, reason="tippecanoe not installed")
async def test_tiles_have_no_filenames(pipe):
    coll = await pipe.collection({})
    ids = await _located(pipe, coll, 3, properties={"owner": "secret-prop"})
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Image).values(filename="secret-name.jpg"))
        await s.commit()
    gen = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.PUBLISHED
    row = await _state(pipe, coll)
    data = await pipe.store.read(row.map_key)
    assert data[:7] == b"PMTiles"
    tiles = _tile_bytes(data)
    assert tiles
    blob = b"".join(tiles)
    assert b"secret-name" not in blob and b"secret-prop" not in blob
    assert b"filename" not in blob and b"owner" not in blob
    assert any(str(i).encode() in blob for i in ids)
    assert row.map_image_count == 3


async def test_the_health_check_reports_missing_tippecanoe(monkeypatch):
    from simple_module_core.health import HealthRegistry, HealthStatus
    from sm_images.module import ImagesModule

    checks = HealthRegistry()
    ImagesModule().register_health_checks(checks)
    (check,) = [c for c in checks.all_checks if c.name == "images.tippecanoe"]
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: None)
    missing = await check.check()
    assert missing.status is HealthStatus.DEGRADED and "tippecanoe" in missing.detail
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: "/usr/bin/tippecanoe")
    assert (await check.check()).status is HealthStatus.HEALTHY
