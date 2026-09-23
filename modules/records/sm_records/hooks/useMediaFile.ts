import { useEffect, useState } from 'react';

import { getMediaFile, type MediaApi, type MediaFile, mediaValueKind } from '../utils/media-api';

/** What a stored `media` value turned out to be, once looked up. */
export type MediaFileState =
  /** No value, or no media library to ask. */
  | { status: 'empty' }
  /** A plain `https://` URL saved before the picker existed — never looked up. */
  | { status: 'url'; url: string }
  /** A `/`-rooted value — already a usable address, a relative link, never
   *  looked up. */
  | { status: 'path'; path: string }
  /** Anything else: legacy or seeded data that was never a `file_storage`
   *  id, shown as the plain text it is — never looked up, never "missing". */
  | { status: 'text'; value: string }
  | { status: 'loading' }
  | { status: 'ready'; file: MediaFile }
  /** The library has no such id: deleted since it was picked. Only an
   *  id-shaped value ever reaches this state — see `mediaValueKind`. */
  | { status: 'missing' }
  | { status: 'error'; message: string };

function initial(api: MediaApi | null, value: string): MediaFileState {
  if (!value) return { status: 'empty' };
  const trimmed = value.trim();
  switch (mediaValueKind(trimmed)) {
    case 'url':
      return { status: 'url', url: trimmed };
    case 'path':
      return { status: 'path', path: trimmed };
    case 'text':
      return { status: 'text', value: trimmed };
    case 'id':
      return api ? { status: 'loading' } : { status: 'empty' };
  }
}

/**
 * Resolve a stored `media` value to the file it names, through the shared
 * metadata cache in `utils/media-api.ts` — so a list page and the editor ask
 * the library once per id, and a file just picked or uploaded is known
 * without asking at all.
 */
export function useMediaFile(api: MediaApi | null, value: string): MediaFileState {
  const [state, setState] = useState<MediaFileState>(() => initial(api, value));

  useEffect(() => {
    const start = initial(api, value);
    setState(start);
    if (start.status !== 'loading' || !api) return;
    let live = true;
    getMediaFile(api, value).then(
      (file) => {
        if (live) setState(file ? { status: 'ready', file } : { status: 'missing' });
      },
      (error: unknown) => {
        if (live) {
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );
    return () => {
      live = false;
    };
  }, [api, value]);

  return state;
}
