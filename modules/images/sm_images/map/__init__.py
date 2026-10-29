"""A collection's map (spec §5): GeoJSON points and a PMTiles archive.

* :mod:`~sm_images.map.points` - which images may be placed (policy, trash,
  redaction gate, a real coordinate), the ``…/points`` page and its bbox;
* :mod:`~sm_images.map.pmtiles_build` - NDJSON and the tippecanoe run;
* :mod:`~sm_images.map.schedule` - the change counter, the rebuild threshold,
  build requests and withdrawals (a visibility change);
* :mod:`~sm_images.map.build` - one fenced build: snapshot, convert, upload,
  publish;
* :mod:`~sm_images.map.tasks` - ``images.build_map`` on the ``images`` queue.
"""
