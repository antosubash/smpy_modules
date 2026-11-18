import type { ImportRow } from '../../utils/api-import';
import { failureText } from '../../utils/api-import';
import { keys, useT } from '../../utils/i18n';

/** What a screen-reader user needs to hear when the step changes: a polite live region, always
 *  mounted so the change is announced, visually hidden. */
export function Announce({ row, uploading }: { row: ImportRow | null; uploading: boolean }) {
  const { t } = useT();
  const copy = keys.events.import.announce;
  let text = '';
  if (uploading) text = t(copy.uploading);
  else if (row?.status === 'staged')
    text = t(copy.preview, {
      total: row.total,
      new: row.counts.new ?? 0,
      update: row.counts.update ?? 0,
      unchanged: row.counts.unchanged ?? 0,
      skip: row.counts.skip ?? 0,
    });
  else if (row?.status === 'done')
    text = t(copy.done, {
      created: row.created,
      updated: row.updated,
      unchanged: row.unchanged,
      skipped: row.skipped,
      failed: row.failed,
    });
  else if (row?.status === 'failed') text = t(copy.failed, { reason: failureText(row.error_code) });
  else if (row) text = t(copy.working);
  return (
    <div role="status" aria-live="polite" className="sr-only" data-testid="events-import-announce">
      {text}
    </div>
  );
}
