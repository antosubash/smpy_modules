import { router } from '@inertiajs/react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import {
  deleteSnapshot,
  type PendingImport,
  requestRestore,
  type Snapshot,
  takeSnapshot,
} from '../utils/snapshotsApi';

/**
 * Actions on the snapshot list, with the reload and error handling in one place.
 *
 * State comes back from Inertia rather than being held here: taking a snapshot
 * changes both the list *and* whether an import is pending, and re-asking the
 * server is the only way those two stay consistent with each other.
 */
export function useSnapshots(initial: Snapshot[], pending: PendingImport | null) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    router.reload({ only: ['snapshots', 'pending'] });
  }, []);

  const guard = useCallback(
    async (work: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await work();
        reload();
        return true;
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Something went wrong';
        setError(message);
        toast.error(message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const take = useCallback(
    (note?: string) =>
      guard(async () => {
        await takeSnapshot(note);
        toast.success('Snapshot taken', {
          description: 'The site as it stands is now a restore point.',
        });
      }),
    [guard],
  );

  const restore = useCallback(
    (snapshot: Snapshot) =>
      guard(async () => {
        await requestRestore(snapshot.id);
        // Straight to the review screen: staging is not the goal, deciding is,
        // and leaving someone on the list would hide the thing they just made.
        router.visit('/pagebuilder/content/review');
      }),
    [guard],
  );

  const remove = useCallback(
    (snapshot: Snapshot) => guard(() => deleteSnapshot(snapshot.id)),
    [guard],
  );

  return {
    snapshots: initial,
    pending,
    busy,
    error,
    reload,
    take,
    restore,
    remove,
  };
}
