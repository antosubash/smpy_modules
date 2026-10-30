import { useEffect, useRef } from 'react';

import { keys, useT } from '../../utils/i18n';

/** A full-size picture over the page: Escape or a click outside closes it. Focus
 *  moves in, stays in (Tab wraps) and returns to what opened it.
 *  Plain markup rather than the console's dialog, which needs the admin shell. */
export function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const { t } = useT();
  const close = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  // The latest onClose without re-running the effect below: it focuses on mount,
  // and an inline callback would make every parent render steal focus back.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key !== 'Tab') return;
      // A modal: Tab cycles inside the dialog, never out to the page behind it.
      const stops = dialog.current?.querySelectorAll<HTMLElement>('button, [href], [tabindex]');
      const first = stops?.[0];
      const last = stops?.[stops.length - 1];
      if (!first || !last) return;
      const at = document.activeElement;
      if (event.shiftKey && at === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && at === last) {
        event.preventDefault();
        first.focus();
      } else if (!dialog.current?.contains(at)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      opener?.focus?.();
    };
  }, []);

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled on window
    <div
      ref={dialog}
      role="dialog"
      aria-modal="true"
      aria-label={t(keys.images.public.viewer)}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      data-testid="images-lightbox"
      onClick={(event) => {
        // Only the backdrop: a click on the picture itself keeps it open.
        if (event.target === event.currentTarget) onClose();
      }}
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
