"""Names and removal of files belonging to an upload."""

from pathlib import Path


def media_file_names(filename: str, variants: dict | None) -> list[str]:
    """The original's name and every variant's, as one upload wrote them."""
    return [filename] + [
        meta["filename"]
        for meta in (variants or {}).values()
        if isinstance(meta, dict) and meta.get("filename")
    ]


def _unlink(root: Path, filename: str, variants: dict | None) -> None:
    """Remove an upload's original and every variant it wrote."""
    for name in media_file_names(filename, variants):
        (root / name).unlink(missing_ok=True)
