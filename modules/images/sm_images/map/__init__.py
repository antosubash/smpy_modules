"""A collection's map (spec §5): GeoJSON points and a PMTiles archive.

* :mod:`~sm_images.map.points` - which images may be placed (policy, trash,
  redaction gate, a real coordinate), the ``…/points`` page and its bbox;
* :mod:`~sm_images.map.pmtiles_build` - NDJSON and the tippecanoe run;
* :mod:`~sm_images.map.schedule` - the change counter, the rebuild threshold
  and build requests;
* :mod:`~sm_images.map.revoke` - withdrawals: a visibility change, a removed
  point, a new redaction gate; an image falling back into redaction-pending;
* :mod:`~sm_images.map.recover` - reconcile's pass: due maps, stale archives;
* :mod:`~sm_images.map.build` - one fenced build: snapshot, convert, upload,
  publish (stamped with the redaction gate it used);
* :mod:`~sm_images.map.objects` - deleting archives nothing references;
* :mod:`~sm_images.map.tasks` - ``images.build_map`` on the ``images`` queue.
"""
