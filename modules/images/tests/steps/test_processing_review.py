"""Task 8 review minors: one EXIF transpose, explicit HEIF registration,
orientation range, and the altitude edge cases."""

from __future__ import annotations

import io
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PIL import Image, ImageOps
from PIL.TiffImagePlugin import IFDRational
from sm_images.processing import renditions
from sm_images.processing.exif import read_exif

FIX = Path(__file__).parent.parent / "fixtures"
GPS = 0x8825


def _jpeg(exif: Image.Exif) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_renditions_transpose_once(monkeypatch) -> None:
    calls: list[int] = []
    real = ImageOps.exif_transpose

    def counted(img, **kw):
        calls.append(1)
        return real(img, **kw)

    monkeypatch.setattr(renditions.ImageOps, "exif_transpose", counted)
    out = renditions.make_renditions((FIX / "rotated.jpg").read_bytes(), {"a": 1024})
    assert out["a"][1:] == (40, 80)
    assert calls == [1]


def test_register_heif_is_explicit_and_idempotent(monkeypatch) -> None:
    from sm_images.processing import heif as _heif

    calls: list[int] = []
    monkeypatch.setattr(_heif, "_registered", False)
    monkeypatch.setattr(_heif.pillow_heif, "register_heif_opener", lambda: calls.append(1))
    _heif.register_heif()
    _heif.register_heif()
    assert calls == [1]


def test_processing_opens_heic_without_the_sniffer() -> None:
    """exif and renditions register HEIF themselves, not through importing
    ``sm_images.ingest.sniff`` for its side effect."""
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from sm_images.processing.exif import read_exif
        from sm_images.processing.renditions import make_renditions
        assert "sm_images.ingest.sniff" not in sys.modules, "imported the sniffer"
        data = Path({str(FIX / "sample.heic")!r}).read_bytes()
        assert read_exif(data).lat is not None
        assert make_renditions(data, {{"a": 32}})["a"][1:] == (32, 24)
        """
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize(("raw", "want"), [(1, 1), (8, 8), (0, None), (9, None), (255, None)])
def test_orientation_outside_1_to_8_is_none(raw: int, want: int | None) -> None:
    exif = Image.Exif()
    exif[0x0112] = raw
    assert read_exif(_jpeg(exif)).orientation == want


def test_positive_altitude_above_sea_level() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS)
    gps[5], gps[6] = 0, IFDRational(2505, 10)
    assert read_exif(_jpeg(exif)).altitude == pytest.approx(250.5)


def test_an_x_over_zero_altitude_is_none() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS)
    gps[5], gps[6] = 0, IFDRational(7, 0)
    assert read_exif(_jpeg(exif)).altitude is None
