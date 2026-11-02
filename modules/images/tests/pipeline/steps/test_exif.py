from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from sm_images.pipeline.processing.exif import ExifData, read_exif

FIX = Path(__file__).parent.parent.parent / "fixtures"
GPS, EXIF_IFD = 0x8825, 0x8769


def _jpeg(exif: Image.Exif) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_geotagged_fixture_exact_values() -> None:
    got = read_exif((FIX / "geotagged.jpg").read_bytes())
    assert got.lat == pytest.approx(-33.865)
    assert got.lng == pytest.approx(-151.21)
    assert got.altitude == pytest.approx(-12.5)
    assert got.heading == pytest.approx(90.0)
    assert got.captured_at == datetime(2024, 3, 5, 14, 30, 15, tzinfo=timezone(timedelta(hours=2)))
    assert (got.make, got.model, got.orientation) == ("Acme", "Cam-1", 1)


def test_frozen() -> None:
    with pytest.raises(AttributeError):
        ExifData().lat = 1.0  # type: ignore[misc]


def test_orientation_fixture() -> None:
    got = read_exif((FIX / "rotated.jpg").read_bytes())
    assert got.orientation == 6
    assert got.lat is None and got.lng is None and got.captured_at is None


def test_png_without_exif_is_all_none() -> None:
    assert read_exif((FIX / "transparent.png").read_bytes()) == ExifData()


def test_exact_zero_zero_means_absent() -> None:
    got = read_exif((FIX / "zero_gps.jpg").read_bytes())
    assert got.lat is None and got.lng is None
    assert got.make == "Acme"


def test_heic_gps_and_naive_time() -> None:
    got = read_exif((FIX / "sample.heic").read_bytes())
    assert got.lat == pytest.approx(48.2)
    assert got.lng == pytest.approx(16.375)
    assert got.captured_at == datetime(2023, 7, 8, 9, 10, 11)
    assert got.captured_at.tzinfo is None
    assert (got.make, got.model) == ("Apple", "iPhone")


def test_garbage_bytes_yield_empty() -> None:
    assert read_exif(b"not an image") == ExifData()


def test_nan_coordinate_means_neither() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS)
    gps[1], gps[2], gps[3], gps[4] = "N", (IFDRational(0, 0), 0.0, 0.0), "E", (10.0, 0.0, 0.0)
    got = read_exif(_jpeg(exif))
    assert got.lat is None and got.lng is None  # both or neither


def test_out_of_range_coordinates_are_none() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS)
    gps[1], gps[2], gps[3], gps[4] = "N", (95.0, 0.0, 0.0), "E", (10.0, 0.0, 0.0)
    assert read_exif(_jpeg(exif)).lat is None


def test_zero_on_one_axis_is_kept() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(GPS)
    gps[1], gps[2], gps[3], gps[4] = "N", (0.0, 0.0, 0.0), "E", (10.0, 0.0, 0.0)
    got = read_exif(_jpeg(exif))
    assert (got.lat, got.lng) == (0.0, 10.0)


def test_datetime_fallback_naive_without_offset() -> None:
    exif = Image.Exif()
    exif[0x0132] = "2021:02:03 04:05:06"
    assert read_exif(_jpeg(exif)).captured_at == datetime(2021, 2, 3, 4, 5, 6)


def test_bad_datetime_is_none() -> None:
    exif = Image.Exif()
    exif.get_ifd(EXIF_IFD)[0x9003] = "garbage"
    assert read_exif(_jpeg(exif)).captured_at is None


def test_nul_stripped_and_camera_truncated() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Ma\x00ke "
    exif[0x0110] = "M" * 150
    got = read_exif(_jpeg(exif))
    assert got.make == "Make"
    assert got.model == "M" * 100


def test_bad_heading_is_none() -> None:
    exif = Image.Exif()
    exif.get_ifd(GPS)[17] = 400.0
    assert read_exif(_jpeg(exif)).heading is None
