"""Regenerate the small image fixtures (run from the repo root with uv run python).

EXIF is written with Pillow's ``Image.Exif`` API. Every file stays under 50 KB.
``real_face.jpg`` and ``real_plate.jpg`` are not generated here: they are CC0
photographs for the ``real_models`` tests (sources in ``test_anonymize_real.py``).
"""

from __future__ import annotations

import io
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()
HERE = Path(__file__).parent

GPS, EXIF_IFD = 0x8825, 0x8769


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    img.putdata([(x * 255 // w, y * 255 // h, 128) for y in range(h) for x in range(w)])
    return img


def _gps_exif(lat, lat_ref, lng, lng_ref, alt=None, alt_ref=0, heading=None) -> Image.Image:
    exif = Image.Exif()
    exif[0x010F] = "Acme\x00"
    exif[0x0110] = "Cam-1\x00\x00"
    exif[0x0132] = "2020:01:01 00:00:00"
    exif[0x0112] = 1
    ifd = exif.get_ifd(EXIF_IFD)
    ifd[0x9003] = "2024:03:05 14:30:15"
    ifd[0x9011] = "+02:00"
    gps = exif.get_ifd(GPS)
    gps[1], gps[2], gps[3], gps[4] = lat_ref, lat, lng_ref, lng
    if alt is not None:
        gps[5], gps[6] = alt_ref, alt
    if heading is not None:
        gps[16], gps[17] = "T", heading
    return exif


def main() -> None:
    img = _gradient(96, 64)
    # 33deg 51' 54" S, 151deg 12' 36" W-ish; altitude 12.5 m below sea level
    img.save(
        HERE / "geotagged.jpg",
        "JPEG",
        quality=80,
        exif=_gps_exif((33.0, 51.0, 54.0), "S", (151.0, 12.0, 36.0), "W", 12.5, 1, 90.0),
    )
    img.save(
        HERE / "zero_gps.jpg",
        "JPEG",
        quality=80,
        exif=_gps_exif((0.0, 0.0, 0.0), "N", (0.0, 0.0, 0.0), "E"),
    )
    rot = Image.Exif()
    rot[0x0112] = 6
    _gradient(80, 40).save(HERE / "rotated.jpg", "JPEG", quality=80, exif=rot)
    heic = Image.Exif()
    heic[0x010F] = "Apple"
    heic[0x0110] = "iPhone"
    heic.get_ifd(EXIF_IFD)[0x9003] = "2023:07:08 09:10:11"
    gps = heic.get_ifd(GPS)
    gps[1], gps[2], gps[3], gps[4] = "N", (48.0, 12.0, 0.0), "E", (16.0, 22.0, 30.0)
    buf = io.BytesIO()
    _gradient(64, 48).save(buf, "HEIF", quality=50, exif=heic.tobytes())
    (HERE / "sample.heic").write_bytes(buf.getvalue())
    alpha = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    alpha.paste((255, 0, 0, 255), (0, 0, 20, 40))
    alpha.save(HERE / "transparent.png")


if __name__ == "__main__":
    main()
