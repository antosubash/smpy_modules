import { type MutableRefObject, useEffect, useRef, useState } from 'react';

import type { TypeRead } from '../utils/types';

/**
 * Keeps the type editor's `current` snapshot in step with the `type` prop
 * without letting a background poll re-baseline its optimistic concurrency.
 *
 * Two things push a new `type` at this page: an ordinary navigation, and
 * `ReindexStatus`' `router.reload({ only: ['type'] })` every ~5s while a
 * reindex is pending (F4). `current` has to follow — it is what
 * `ReindexStatus` itself reads, so a snapshot frozen at mount meant the
 * banner and the poll outlived the rebuild.
 *
 * But `current.version` is also what Save sends as `expected_version`
 * (R15). Adopting a polled version wholesale meant that if someone else
 * saved the type during that window, this draft's next Save carried *their*
 * version with *this* draft's fields and overwrote their change — the one
 * path that defeats the version check by construction, since the 409
 * `useSchemaApply` exists to handle could never be raised.
 *
 * So: a newer version arriving under a *dirty* draft keeps the version the
 * draft was opened against, takes only the `reindex_pending` the poll went
 * to fetch, and reports the newer type as `externalChange` — which the page
 * renders through the same "this type changed while you were editing"
 * notice a 409 produces. A clean draft still adopts silently: there is
 * nothing to lose and nothing to warn about.
 */
export function useTypeSync(type: TypeRead | null): {
  current: TypeRead | null;
  externalChange: TypeRead | null;
  /** Take a type the server just handed back (a save, a reload from the
   *  conflict notice) as the new baseline. */
  adopt: (saved: TypeRead) => void;
  /** The page writes its own dirty flag here during render; the effect
   *  reads it so a change to `dirty` alone never re-runs the sync. */
  dirtyRef: MutableRefObject<boolean>;
} {
  const [current, setCurrent] = useState<TypeRead | null>(type);
  const [externalChange, setExternalChange] = useState<TypeRead | null>(null);
  const dirtyRef = useRef(false);
  const currentRef = useRef(current);
  currentRef.current = current;

  useEffect(() => {
    const prev = currentRef.current;
    if (!type || !prev || type.version === prev.version || !dirtyRef.current) {
      setCurrent(type);
      setExternalChange(null);
      return;
    }
    setCurrent({ ...prev, reindex_pending: type.reindex_pending });
    setExternalChange(type);
  }, [type]);

  return {
    current,
    externalChange,
    adopt: (saved: TypeRead) => {
      setExternalChange(null);
      setCurrent(saved);
    },
    dirtyRef,
  };
}
