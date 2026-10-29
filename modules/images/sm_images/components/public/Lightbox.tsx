import { useEffect, useRef } from 'react';

import { keys, useT } from '../../utils/i18n';

/** A full-size picture over the page: Escape or a click outside closes it.
 *  Plain markup rather than the console's dialog, which needs the admin shell. */
export function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const { t } = useT();
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled on window
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t(keys.images.public.viewer)}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      data-testid="images-lightbox"
      onClick={onClose}
    >
      <button
        ref={close}
        type="button"
        className="absolute right-4 top-4 rounded bg-background px-3 py-1 text-sm"
        onClick={onClose}
      >
        {t(keys.images.public.close)}
      </button>
      <img
        src={src}
        alt={alt}
        className="max-h-full max-w-full rounded object-contain"
        data-testid="images-lightbox-image"
      />
    </div>
  );
}
