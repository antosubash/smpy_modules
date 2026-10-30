import { useCallback, useRef, useState } from 'react';

import { type GeoJsonPreview, previewGeoJson } from '../utils/geojsonPreview';

/**
 * The picked GeoJSON file and its preview, read once per pick. Each pick takes
 * a ticket; a preview that finishes after a newer pick (or a clear) is dropped,
 * so a slow read of an old file can never overwrite the current one. Editing
 * the mapping afterwards never re-reads the file.
 */
export function useGeoJsonPreview() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<GeoJsonPreview | null>(null);
  const [reading, setReading] = useState(false);
  const latest = useRef(0);

  const pick = useCallback(async (next: File, onRead: (preview: GeoJsonPreview) => void) => {
    const ticket = ++latest.current;
    setFile(next);
    setPreview(null);
    setReading(true);
    const read = await previewGeoJson(next);
    if (ticket !== latest.current) return;
    setPreview(read);
    setReading(false);
    onRead(read);
  }, []);

  const clear = useCallback(() => {
    latest.current++;
    setFile(null);
    setPreview(null);
    setReading(false);
  }, []);

  return { file, preview, reading, pick, clear };
}
