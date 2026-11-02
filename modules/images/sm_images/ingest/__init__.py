"""Ingest: every path by which an image enters a collection ends in
:meth:`IngestService.add_image`."""

from __future__ import annotations

from sm_images.ingest.guards import Inspected, guard_pixels, inspect
from sm_images.ingest.meta import IngestMeta, UploadMeta, parse_batch_metadata
from sm_images.ingest.service import Duplicate, IngestService, Slot, safe_filename
from sm_images.ingest.sniff import sniff

__all__ = [
    "Duplicate",
    "IngestMeta",
    "IngestService",
    "Inspected",
    "Slot",
    "UploadMeta",
    "guard_pixels",
    "inspect",
    "parse_batch_metadata",
    "safe_filename",
    "sniff",
]
