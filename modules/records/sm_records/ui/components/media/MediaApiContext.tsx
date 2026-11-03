import { createContext, type ReactNode, useContext, useMemo } from 'react';

import type { MediaApi } from '../../utils/media-api';

/**
 * The `media_api` view prop, handed to every `media` field and cell below the
 * page that received it — the editor's form and the list's table are several
 * components deep, and a prop threaded through each of them would reach
 * `FieldComponentProps`, which every field type shares and only one reads.
 *
 * `null` (the default, and what a page without the prop gets) means the host
 * has no media library: the field is the plain text box and a cell shows the
 * stored id as text.
 */
const MediaApiContext = createContext<MediaApi | null>(null);

export function MediaApiProvider({
  value,
  children,
}: {
  value: MediaApi | null | undefined;
  children: ReactNode;
}) {
  // Keyed by content, not identity: an Inertia partial reload hands back a
  // fresh props object, and every metadata lookup keyed on this would re-run.
  const key = value ? JSON.stringify(value) : '';
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` is `value`'s content
  const stable = useMemo(() => value ?? null, [key]);
  return <MediaApiContext.Provider value={stable}>{children}</MediaApiContext.Provider>;
}

export function useMediaApi(): MediaApi | null {
  return useContext(MediaApiContext);
}
