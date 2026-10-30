import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect } from 'react';

import { keys, useT } from '../../utils/i18n';

export type Neighbors = { prev: string | null; next: string | null };

const viewerUrl = (id: string) => `/admin/images/images/${id}`;

/** Where an arrow key belongs to the control, not to the viewer. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.tagName !== 'string') return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable;
}

const OVERLAY =
  '[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"],[aria-modal="true"]';

/** An open dialog or menu owns the keyboard, wherever the focus happens to be. */
function overlayOpen(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (el && typeof el.closest === 'function' && el.closest(OVERLAY)) return true;
  return document.querySelector(OVERLAY) !== null;
}

/**
 * Previous / next image in the gallery's order (`neighbors`, from the server:
 * only images this person may open), as buttons and as ← / → anywhere on the
 * page except inside a field or while a dialog or menu is open.
 */
export function NeighborNav({ neighbors }: { neighbors: Neighbors }) {
  const { t } = useT();
  const { prev, next } = neighbors;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.defaultPrevented || typing(event.target) || overlayOpen(event.target)) return;
      const to = event.key === 'ArrowLeft' ? prev : event.key === 'ArrowRight' ? next : null;
      if (!to) return;
      event.preventDefault();
      router.visit(viewerUrl(to));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [prev, next]);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        disabled={!prev}
        aria-keyshortcuts="ArrowLeft"
        data-testid="images-viewer-prev"
        onClick={() => prev && router.visit(viewerUrl(prev))}
      >
        {t(keys.images.viewer.previous)}
      </Button>
      <Button
        type="button"
        variant="outline"
        disabled={!next}
        aria-keyshortcuts="ArrowRight"
        data-testid="images-viewer-next"
        onClick={() => next && router.visit(viewerUrl(next))}
      >
        {t(keys.images.viewer.next)}
      </Button>
    </>
  );
}
