"""ZIP archives to test against: honest ones, and ones whose headers lie.

``make_zip`` writes members in order (duplicate names allowed). The forgeries
patch the archive's own bytes - the central directory *and* each local header -
so ``zipfile`` reads exactly what a hostile client would send.
"""

from __future__ import annotations

import io
import stat
import struct
import warnings
import zipfile
from collections.abc import Iterable

CD_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"


def make_zip(
    members: Iterable[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names are deliberate
        with zipfile.ZipFile(buf, "w", compression=compression) as zf:
            for name, data in members:
                zf.writestr(name, data)
    return buf.getvalue()


def with_symlink(name: str, target: bytes = b"/etc/passwd") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, target)
    return buf.getvalue()


def _patch_all(data: bytes, sig: bytes, offset: int, fmt: str, value: int | None, bit=0) -> bytes:
    out = bytearray(data)
    at = out.find(sig)
    while at >= 0:
        if value is not None:
            struct.pack_into(fmt, out, at + offset, value)
        else:
            (flags,) = struct.unpack_from(fmt, out, at + offset)
            struct.pack_into(fmt, out, at + offset, flags | bit)
        at = out.find(sig, at + 4)
    return bytes(out)


def lie_sizes(data: bytes, size: int) -> bytes:
    """Every member claims ``size`` uncompressed bytes (CRCs stay honest)."""
    data = _patch_all(data, CD_SIG, 24, "<L", size)
    return _patch_all(data, LOCAL_SIG, 22, "<L", size)


def encrypted(data: bytes) -> bytes:
    """Every member's "encrypted" flag set (the bytes are not)."""
    data = _patch_all(data, CD_SIG, 8, "<H", None, 0x1)
    return _patch_all(data, LOCAL_SIG, 6, "<H", None, 0x1)


def overlapping(name: bytes = b"a.jpg", other: bytes = b"b.jpg", body: bytes = b"x" * 64) -> bytes:
    """Two central entries pointing at one local header: a non-recursive bomb."""
    single = make_zip([(name.decode(), body)], zipfile.ZIP_STORED)
    eocd_at = single.rfind(b"PK\x05\x06")
    (cd_size,) = struct.unpack("<L", single[eocd_at + 12 : eocd_at + 16])
    (cd_offset,) = struct.unpack("<L", single[eocd_at + 16 : eocd_at + 20])
    entry = single[cd_offset : cd_offset + cd_size]
    central = entry + entry.replace(name, other)
    eocd = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 2, 2, len(central), cd_offset, 0)
    return single[:cd_offset] + central + eocd


# --- A ZIP job through the real upload and seal, against ``imp``'s store. ---

SECRET = "zip-test-secret"


async def _one(data: bytes):
    yield data


async def upload_zip(imp, data: bytes, *, mapping=None, coll=None):
    """Start a ZIP job and write its parts the way the relay route does;
    ``(job_id, ticket)``. Not sealed yet."""
    from sm_images.imports import zip_upload
    from sm_images.tenancy import DEFAULT_TENANT

    job, (_token, ticket, _urls, _direct) = await zip_upload.start(
        imp.runtime,
        DEFAULT_TENANT,
        coll or imp.coll,
        filename="photos.zip",
        size=len(data),
        mapping=mapping,
        owner="olga",
        secret=SECRET,
    )
    for n in range(1, ticket.parts + 1):
        chunk = data[(n - 1) * ticket.part_size : n * ticket.part_size]
        await imp.pipe.backend.write_part(
            ticket.key, ticket.upload, n, _one(chunk), max_bytes=ticket.part_bytes(n)
        )
    return job.id, ticket


async def sealed_zip(imp, data: bytes, **kw):
    """``(job, generation)``: uploaded and sealed, not yet run."""
    from types import SimpleNamespace

    from sm_images.imports import zip_upload
    from sm_images.tenancy import DEFAULT_TENANT

    job_id, _ = await upload_zip(imp, data, **kw)
    generation = await zip_upload.seal(imp.runtime, DEFAULT_TENANT, job_id, {})
    return SimpleNamespace(id=job_id), generation


async def run_zip(imp, job, generation: int) -> str:
    from sm_images.imports import zip_import
    from sm_images.tenancy import DEFAULT_TENANT

    return await zip_import.import_zip_async(imp.runtime, DEFAULT_TENANT, job.id, generation)


async def import_zip(imp, data: bytes, **kw):
    """``(job, status)``: uploaded, sealed and run."""
    job, generation = await sealed_zip(imp, data, **kw)
    return job, await run_zip(imp, job, generation)
