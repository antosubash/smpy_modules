import { useEffect, useRef } from 'react';

export type ReviewKeyHandlers = {
  next: () => void;
  previous: () => void;
  accept: () => void;
  reject: () => void;
  edit: () => void;
  cancel: () => void;
  /** While the correction form is open only Escape is a shortcut. */
  editing: boolean;
};

const TYPING = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

/** The review queue's keyboard path: j/k move, a accept, r reject, e correct
 *  (Escape leaves the form). Ignored while typing and with a modifier held. */
export function useReviewKeys(handlers: ReviewKeyHandlers): void {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const typing = target !== null && (TYPING.has(target.tagName) || target.isContentEditable);
      const h = ref.current;
      if (event.key === 'Escape' && h.editing) return h.cancel();
      if (typing || h.editing) return;
      const action = {
        j: h.next,
        k: h.previous,
        a: h.accept,
        r: h.reject,
        e: h.edit,
      }[event.key];
      if (!action) return;
      event.preventDefault();
      action();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
