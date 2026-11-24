import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';
import { HttpError } from '../utils/http';
import { keys, useT } from '../utils/i18n';
import { useMountedRef } from './useMountedRef';
import { useWriteQueue } from './useWriteQueue';

/** Every callback is an explicitly requested write. Drain those after navigation
 * with send-time versions, stopping at the first failure once the screen is gone.
 * The body editor keeps its separate autosave/final-flush queue. */
export function useArticleWriteQueue() {
  const { t } = useT();
  const mounted = useMountedRef();
  const queue = useWriteQueue();
  const blocked = useRef(false);
  const failed = useRef(false);
  const [conflict, setConflict] = useState(false);
  const [error, setErrorState] = useState<string | null>(null);
  const setError = useCallback(
    (message: string | null) => {
      if (mounted.current) setErrorState(message);
    },
    [mounted],
  );
  const reset = useCallback(() => {
    blocked.current = false;
    failed.current = false;
    if (mounted.current) setConflict(false);
    setError(null);
  }, [mounted, setError]);

  const runWrite = useCallback(
    (action: () => Promise<void>, notify = false) =>
      queue(async () => {
        if (!mounted.current && failed.current) return false;
        try {
          if (blocked.current) {
            throw new HttpError(t(keys.news.errors.article_conflict), 409, 'article_conflict');
          }
          setError(null);
          await action();
          failed.current = false;
          // Callers use this to show success or navigate: neither belongs to a
          // screen the writer has left, even though its request succeeded.
          return mounted.current;
        } catch (e) {
          failed.current = true;
          if (e instanceof HttpError && e.code === 'article_conflict') blocked.current = true;
          if (!mounted.current) {
            console.warn('Article write failed after leaving the editor', e);
            return false;
          }
          setConflict(blocked.current);
          setError((e as Error).message);
          if (notify) toast.error((e as Error).message);
          return false;
        }
      }),
    [mounted, queue, setError, t],
  );

  return { mounted, runWrite, reset, error, setError, conflict };
}
