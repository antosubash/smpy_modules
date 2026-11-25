import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { HttpError } from '../utils/http';
import { keys, useT } from '../utils/i18n';
import { useMountedRef } from './useMountedRef';
import { useWriteQueue } from './useWriteQueue';

/** Every callback is an explicitly requested write. Drain those after navigation
 * with send-time versions, stopping at the first failure once the screen is gone.
 * The body editor keeps its separate autosave/final-flush queue. */
export function useArticleWriteQueue(articleId: number) {
  const { t } = useT();
  const mounted = useMountedRef(articleId);
  const queue = useWriteQueue();
  const [flags, setFlags] = useState({
    articleId,
    blocked: false,
    failed: false,
    stopped: false,
    toastId: undefined as string | number | undefined,
  });
  const [conflict, setConflict] = useState(false);
  const [error, setErrorState] = useState<string | null>(null);
  // A write found no article: it was trashed or purged under the editor. Stays
  // set, and stops later writes, until Reload or another article resets it.
  const [missing, setMissing] = useState(false);
  if (flags.articleId !== articleId) {
    setFlags({ articleId, blocked: false, failed: false, stopped: false, toastId: undefined });
    setConflict(false);
    setErrorState(null);
    setMissing(false);
  }
  const setError = useCallback(
    (message: string | null) => {
      if (mounted.current) setErrorState(message);
    },
    [mounted],
  );
  const reset = useCallback(() => {
    flags.blocked = false;
    flags.failed = false;
    flags.stopped = false;
    flags.toastId = undefined;
    if (mounted.current) setConflict(false);
    if (mounted.current) setMissing(false);
    setError(null);
  }, [flags, mounted, setError]);

  const runWrite = useCallback(
    (action: () => Promise<void>, notify = false, terminal = false) =>
      queue(async () => {
        if (flags.stopped || (!mounted.current && flags.failed)) return false;
        try {
          if (flags.blocked) {
            throw new HttpError(t(keys.news.errors.article_conflict), 409, 'article_conflict');
          }
          setError(null);
          await action();
          flags.failed = false;
          if (terminal) flags.stopped = true;
          // Callers use this to show success or navigate: neither belongs to a
          // screen the writer has left, even though its request succeeded.
          return mounted.current;
        } catch (e) {
          flags.failed = true;
          if (e instanceof HttpError && e.code === 'article_conflict') flags.blocked = true;
          if (!mounted.current) {
            // Server details and arbitrary thrown errors can contain the input.
            console.warn('Article write failed after leaving the editor', {
              status: e instanceof HttpError ? e.status : undefined,
            });
            return false;
          }
          // By code, not status: a missing revision is a 404 on a live article.
          const vanished = e instanceof HttpError && e.code === 'article_not_found';
          if (vanished) flags.stopped = true;
          // The server's "not found" says less than what happened to the article.
          const message = vanished ? t(keys.news.errors.gone) : (e as Error).message;
          setConflict(flags.blocked);
          if (vanished) setMissing(true);
          setError(message);
          if (notify) {
            const id = flags.blocked ? flags.toastId : undefined;
            const shown = id === undefined ? toast.error(message) : toast.error(message, { id });
            if (flags.blocked) flags.toastId = shown;
          }
          return false;
        }
      }),
    [flags, mounted, queue, setError, t],
  );

  return { mounted, runWrite, reset, error, setError, conflict, missing };
}
