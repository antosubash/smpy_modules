import { useCallback, useEffect, useRef, useState } from 'react';

import { listPublicImages, publicDisplayUrl } from '../../utils/api-public';
import { keys, useT } from '../../utils/i18n';
import type { PublicImage } from '../../utils/types-public';
import { Lightbox } from './Lightbox';

export type TileSize = 'small' | 'medium' | 'large';

/** Grid classes per tile size: more columns means smaller tiles. */
const GRID: Record<TileSize, string> = {
  small: 'grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8',
  medium: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5',
  large: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3',
};

type Props = {
  slug: string;
  /** Names the pictures for assistive tech; the list carries no filenames. */
  name: string;
  size?: TileSize;
  /** Show at most this many and no "load more" (the pagebuilder block). */
  count?: number;
  /** `imageId` to open from outside (a click on the map). */
  openId?: string | null;
  onClosed?: () => void;
};

/** A public collection's thumbnails (the anonymous twin's `small` renditions)
 *  and, on click, the display copy in a lightbox. Reads only public routes, so
 *  it works for a visitor with no session. */
export function PublicGallery({
  slug,
  name,
  size = 'medium',
  count,
  openId = null,
  onClosed,
}: Props) {
  const { t } = useT();
  const [items, setItems] = useState<PublicImage[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [opened, setOpened] = useState<string | null>(null);

  // Aborts every request of the current slug (the first page and each "load
  // more") when the slug changes or the gallery unmounts.
  const controller = useRef<AbortController | null>(null);
  // The cursor being read: a second click on "load more" must not append the page twice.
  const reading = useRef<string | null>(null);

  const load = useCallback(
    async (cursor: string | null, signal?: AbortSignal) => {
      if (cursor !== null) {
        if (reading.current === cursor) return;
        reading.current = cursor;
      }
      try {
        const page = await listPublicImages(slug, { limit: count, cursor, signal });
        if (signal?.aborted) return;
        setItems((rows) => (cursor ? [...rows, ...page.items] : page.items));
        setNext(count ? null : page.next_cursor);
        setState('ready');
      } catch {
        if (!signal?.aborted) setState('failed');
      } finally {
        if (reading.current === cursor) reading.current = null;
      }
    },
    [slug, count],
  );

  useEffect(() => {
    const own = new AbortController();
    controller.current = own;
    reading.current = null;
    setItems([]);
    setNext(null);
    setState('loading');
    void load(null, own.signal);
    return () => own.abort();
  }, [load]);

  const shown = opened ?? openId;
  const close = () => {
    setOpened(null);
    onClosed?.();
  };
  const current = items.find((i) => i.id === shown);
  const lightboxSrc = shown ? (current?.display_url ?? publicDisplayUrl(slug, shown)) : null;

  // A visitor's broken API shows nothing rather than an error box, except on the
  // collection's own page, where an empty gallery would read as an empty collection.
  if (state === 'failed') {
    return count ? (
      <></>
    ) : (
      <p role="alert" className="text-sm text-destructive">
        {t(keys.images.public.failed)}
      </p>
    );
  }
  if (state === 'ready' && items.length === 0) {
    return count ? <></> : <p className="text-muted-foreground">{t(keys.images.public.empty)}</p>;
  }
  return (
    <div className="space-y-4">
      <div className={`grid gap-3 ${GRID[size]}`} data-testid="images-public-gallery">
        {items.map((image, index) => (
          <button
            key={image.id}
            type="button"
            className="aspect-square overflow-hidden rounded-md border bg-muted"
            aria-label={t(keys.images.public.open)}
            data-testid="images-public-tile"
            onClick={() => setOpened(image.id)}
          >
            <img
              src={image.thumb_url}
              alt={t(keys.images.public.image_alt, { index: index + 1, name })}
              loading="lazy"
              className="size-full object-cover"
            />
          </button>
        ))}
      </div>
      {next && (
        <button
          type="button"
          className="rounded-md border px-4 py-2 text-sm"
          data-testid="images-public-more"
          onClick={() => void load(next, controller.current?.signal)}
        >
          {t(keys.images.public.load_more)}
        </button>
      )}
      {lightboxSrc && <Lightbox src={lightboxSrc} alt={name} onClose={close} />}
    </div>
  );
}
