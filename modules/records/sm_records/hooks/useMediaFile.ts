import { useEffect, useState } from 'react';

import { getMediaFile, isUrlValue, type MediaApi, type MediaFile } from '../utils/media-api';

/** What a stored `media` value turned out to be, once looked up. */
export type MediaFileState =
  /** No value, or no media library to ask. */
  | { status: 'empty' }
  /** A plain `https://` URL saved before the picker existed — never looked up. */
  | { status: 'url'; url: string }
  | { status: 'loading' }
  | { status: 'ready'; file: MediaFile }
  /** The library has no such file: deleted since it was picked, or a value
   *  that was never one of its ids. The value is kept as it is. */
  | { status: 'missing' }
  | { status: 'error'; message: string };

function initial(api: MediaApi | null, value: string): MediaFileState {
  if (!value) return { status: 'empty' };
  if (isUrlValue(value)) return { status: 'url', url: value };
  return api ? { status: 'loading' } : { status: 'empty' };
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
