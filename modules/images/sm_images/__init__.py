"""Images - collections of images with a processing pipeline.

Originals are immutable. Derived data (EXIF, renditions, quality metrics, an
optionally anonymised display copy, map tiles) is produced by pipeline steps
that run as background tasks. Design:
``docs/superpowers/specs/2026-10-28-images-module-design.md``.
"""
