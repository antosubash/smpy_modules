"""ZIP imports end to end against an eager runtime: upload, seal, extract.

Every refusal is decided before an item exists; every entry is one item at its
place in the archive; metadata.json and filename patterns feed the images.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from sm_images.core.errors import FileTooLarge
from sm_images.imports import zip_upload
from sm_images.models.enums import JobStatus
from sm_images.tenancy import DEFAULT_TENANT

from tests.support.pipeline import jpeg
from tests.support.zip import import_zip, lie_sizes, make_zip, run_zip, sealed_zip, upload_zip

pytestmark = pytest.mark.asyncio


def _errors(job) -> list[str]:
    return [e["code"] for e in job.errors]


async def _nothing_imported(imp, job) -> None:
    assert await imp.items(job) == []
    assert await imp.images() == []
    assert [k for k in imp.stored() if "/imports/" in k] == []  # the failed job's source went


async def test_each_entry_is_one_item_in_archive_order(imp):
    data = make_zip(
        [
            ("a.jpg", jpeg((8, 6), "red")),
            ("dir/b.jpg", jpeg((8, 6), "blue")),
            ("b.jpg", jpeg((8, 6), "green")),  # the same basename: its own image
            ("notes.txt", b"not an image"),
            ("dir/", b""),
        ]
    )
    job, status = await import_zip(imp, data)
    assert status == "completed"
    items = await imp.items(job)
    assert [(i.feature_index, i.status.value) for i in items] == [
        (0, "done"),
        (1, "done"),
        (2, "done"),
        (3, "failed"),
    ]
    assert items[3].last_error == "unsupported_type"
    assert sorted(i.filename for i in await imp.images()) == ["a.jpg", "b.jpg", "b.jpg"]
    assert await imp.counts(job) == ("completed", 4, 4, 3, 0, 1)
    row = await imp.reload(job)
    assert row.source_key is not None  # failures: kept for retry-failed, as base64


async def test_zip_slip_rejected(imp):
    for bad in ("../../evil.jpg", "/etc/evil.jpg", "C:\\evil.jpg"):
        data = make_zip([("ok.jpg", jpeg()), (bad, jpeg((9, 9), "blue"))])
        job, status = await import_zip(imp, data)
        assert status == "failed", bad
        row = await imp.reload(job)
        assert (row.status, _errors(row)) == (JobStatus.FAILED, ["unsafe_path"])
        await _nothing_imported(imp, job)


async def test_zip_total_uncompressed_cap(imp):
    """The headers claim 30 bytes in all; the entries really hold far more.
    The cap is enforced on what is decompressed, before any item exists."""
    imp.pipe.settings.zip_max_total_bytes = 1500
    members = [(f"{c}.jpg", jpeg((32, 32), c)) for c in ("red", "blue", "green")]
    assert sum(len(m[1]) for m in members) > 1500
    job, status = await import_zip(imp, lie_sizes(make_zip(members), 10))
    assert status == "failed"
    assert _errors(await imp.reload(job)) == ["uncompressed_too_large"]
    await _nothing_imported(imp, job)


async def test_zip_entry_cap(imp):
    imp.pipe.settings.zip_max_entries = 2
    job, _ = await import_zip(imp, make_zip([(f"{i}.jpg", jpeg()) for i in range(3)]))
    assert _errors(await imp.reload(job)) == ["too_many_entries"]
    await _nothing_imported(imp, job)

    imp.pipe.settings.zip_max_entries = 100
    imp.pipe.settings.zip_max_entry_bytes = 1000
    big = jpeg((64, 64), "red") + os.urandom(2000)
    job, _ = await import_zip(imp, lie_sizes(make_zip([("big.jpg", big)]), 10))
    assert _errors(await imp.reload(job)) == ["entry_too_large"]
    await _nothing_imported(imp, job)


async def test_an_image_over_max_image_bytes_fails_alone(imp):
    imp.pipe.settings.max_image_bytes = 1500
    small, big = jpeg((8, 6), "red"), jpeg((64, 64), "blue") + os.urandom(2000)
    job, status = await import_zip(imp, make_zip([("small.jpg", small), ("big.jpg", big)]))
    assert status == "completed"
    assert [(i.status.value, i.last_error) for i in await imp.items(job)] == [
        ("done", None),
        ("failed", "file_too_large"),
    ]


async def test_replaced_object_after_seal_rejected(imp):
    """A presigned PUT may still be valid after the seal: the object extraction
    reads must be the one sealed - same size and fingerprint - or nothing."""
    data = make_zip([("a.jpg", jpeg((8, 6), "red"))])
    for swap in (
        make_zip([("a.jpg", jpeg((8, 6), "blue"))]),  # other bytes
        data[:-1] + bytes([data[-1] ^ 1]),  # one bit, same size
        data + b"\x00" * 10,  # a larger object
    ):
        job, generation = await sealed_zip(imp, data)
        key = (await imp.reload(job)).source_key
        await imp.pipe.store.put(key, swap, content_type="application/zip", size=len(swap))
        assert await run_zip(imp, job, generation) == "failed"
        assert _errors(await imp.reload(job)) == ["archive_changed"]
        assert await imp.images() == []


async def test_the_sealed_archive_must_match_its_declared_size_and_limit(imp):
    job_id, ticket = await upload_zip(imp, make_zip([("a.jpg", jpeg())]))
    imp.pipe.settings.zip_max_bytes = 10  # lowered after the upload started
    with pytest.raises(FileTooLarge):
        await zip_upload.seal(imp.runtime, DEFAULT_TENANT, job_id, {})

    class J:
        id = job_id

    row = await imp.reload(J)
    assert (row.status, _errors(row)) == (JobStatus.FAILED, ["file_too_large"])
    assert not [k for k in imp.stored() if k == ticket.key]


async def test_zip_metadata_json_applied(imp):
    meta = {
        "a.jpg": {
            "latitude": 47.3,
            "longitude": 8.5,
            "external_id": 42,
            "captured_at": "2024-05-01T10:00:00Z",
            "external_metadata": {"plot": "P1"},
            "unknown": "ignored",
        },
        "dir/b.jpg": {"lat": 1.5, "lng": 2.5, "group_key": "G1", "group_role": "NORTH"},
    }
    data = make_zip(
        [
            ("metadata.json", json.dumps(meta).encode()),
            ("photos/a.jpg", jpeg((8, 6), "red")),  # found by its basename, as the portal
            ("dir/b.jpg", jpeg((8, 6), "blue")),  # found by its full path
        ]
    )
    job, status = await import_zip(imp, data)
    assert status == "completed"
    by_name = {i.filename: i for i in await imp.images()}
    a, b = by_name["a.jpg"], by_name["b.jpg"]
    assert (a.lat, a.lng, a.external_id) == (47.3, 8.5, "42")
    assert a.captured_at == datetime(2024, 5, 1, 10, tzinfo=UTC)
    assert a.properties == {"plot": "P1"}
    groups = await imp.groups()
    assert (b.lat, b.lng, b.group_id, b.group_role) == (1.5, 2.5, groups["G1"], "north")
    assert len(await imp.items(job)) == 2  # metadata.json is not an entry


async def test_invalid_metadata_json_fails_the_job(imp):
    bad = json.dumps({"a.jpg": {"latitude": 500}}).encode()
    job, status = await import_zip(imp, make_zip([("metadata.json", bad), ("a.jpg", jpeg())]))
    assert status == "failed"
    assert _errors(await imp.reload(job)) == ["metadata_invalid"]
    await _nothing_imported(imp, job)


async def test_zip_groups_by_pattern(imp):
    pattern = r"^(?P<group>P\d+)_(?P<role>[a-z]+)"
    members = [
        ("site/P1_north.jpg", jpeg((8, 6), "red")),
        ("site/P1_point.jpg", jpeg((8, 6), "blue")),
        ("P2_up.jpg", jpeg((8, 6), "green")),
        ("loose.jpg", jpeg((8, 6), "white")),
    ]
    _, status = await import_zip(imp, make_zip(members), mapping={"filename_pattern": pattern})
    assert status == "completed"
    groups = await imp.groups()
    assert set(groups) == {"P1", "P2"}
    by_name = {i.filename: i for i in await imp.images()}
    assert (by_name["P1_north.jpg"].group_id, by_name["P1_north.jpg"].group_role) == (
        groups["P1"],
        "north",
    )
    assert by_name["P1_point.jpg"].group_role == "point"
    assert (by_name["P2_up.jpg"].group_id, by_name["P2_up.jpg"].group_role) == (groups["P2"], None)
    assert by_name["loose.jpg"].group_id is None


async def test_a_zip_maps_nothing_but_a_filename_pattern(imp):
    from sm_images.core.errors import Invalid

    for mapping in ({"url_prop": "u"}, {"filename_pattern": "(?P<x>a)"}, {"nope": 1}):
        with pytest.raises(Invalid) as err:
            await upload_zip(imp, make_zip([("a.jpg", jpeg())]), mapping=mapping)
        assert err.value.code == "invalid_mapping"
