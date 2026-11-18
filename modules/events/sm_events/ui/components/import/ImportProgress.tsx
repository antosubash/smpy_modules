import type { ImportRow } from '../../utils/api-import';
import { keys, useT } from '../../utils/i18n';

/** An import a worker holds: what it is doing, and how far it is. */
export function ImportProgress({ row }: { row: ImportRow }) {
  const { t } = useT();
  const copy = keys.events.import.progress;
  const text =
    row.status === 'running'
      ? t(copy.running, { done: row.processed, total: row.total })
      : t(
          copy[
            row.status === 'parsing' ? 'parsing' : row.status === 'queued' ? 'queued' : 'uploaded'
          ],
        );
  return (
    <div role="status" className="space-y-2">
      <p>{text}</p>
      {row.status === 'running' && row.total > 0 && (
        <progress className="w-64" value={row.processed} max={row.total} />
      )}
    </div>
  );
}
