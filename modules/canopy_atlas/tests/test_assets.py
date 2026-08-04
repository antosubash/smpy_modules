"""The brand assets ship inside the wheel, not in the host's static directory.

They used to live under ``host/static/gca/``, which meant a host that installed
this module still had to copy files by hand before its own seeded pages would
render.
"""

from __future__ import annotations

from importlib.resources import files

STATIC = files("canopy_atlas") / "static"

EXPECTED_PHOTOS = {
    "atlas-map.jpg",
    "biodiversity.jpg",
    "canopy-aerial.jpg",
    "canopy-up.jpg",
    "collaboration.jpg",
    "forest-aerial-river.jpg",
    "governance-diagram.jpg",
    "hero-lidar.jpg",
}

EXPECTED_PARTNERS = {
    "bristol.svg",
    "erc.svg",
    "esa.svg",
    "geo-trees.svg",
    "iiasa.svg",
    "leverhulme.svg",
    "ukri.svg",
}


def test_ships_the_photographs() -> None:
    names = {p.name for p in (STATIC / "gca" / "images").iterdir()}
    assert names >= EXPECTED_PHOTOS


def test_photographs_are_the_real_files_not_stubs() -> None:
    # Guards against a move that copies the paths but loses the bytes.
    for name in EXPECTED_PHOTOS:
        size = len((STATIC / "gca" / "images" / name).read_bytes())
        assert size > 20_000, f"{name} is {size} bytes — looks like a placeholder"


def test_ships_the_brand_lockups() -> None:
    assert (STATIC / "gca" / "logo-main.svg").is_file()
    assert (STATIC / "gca" / "logo-reversed.svg").is_file()


def test_ships_the_partner_marks() -> None:
    names = {p.name for p in (STATIC / "gca" / "partners").iterdir()}
    assert names >= EXPECTED_PARTNERS


def test_ships_the_design_pack_stylesheet() -> None:
    css = (STATIC / "gca-pack.css").read_text()
    assert ".gca-root" in css
    # The pack owns type, layout and neutrals — not the action colour, which
    # follows Settings → Branding through the primary ramp.
    assert "--color-primary-800: var(--primary)" in css
