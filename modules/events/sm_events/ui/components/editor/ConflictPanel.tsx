import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import type { Difference } from '../../utils/event-diff';
import { keys, useT } from '../../utils/i18n';

/** Shown when a save met a newer revision (409 `stale`). Their version is already
 *  loaded as the base, and the form still holds yours: nothing is retried on its
 *  own. Loading theirs discards your edits; saving yours replaces theirs for the
 *  fields listed, with an explicit click and the new revision. */
export function ConflictPanel({
  differences,
  busy,
  onLoadTheirs,
  onSaveMine,
}: {
  differences: Difference[];
  busy: boolean;
  onLoadTheirs: () => void;
  onSaveMine: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.conflict;
  return (
    <section
      className="grid gap-3 rounded-md border border-destructive p-4"
      aria-label={t(copy.title)}
    >
      <h3 role="alert" className="font-medium text-destructive dark:text-red-400">
        {t(copy.title)}
      </h3>
      <p className="text-sm">{t(copy.description)}</p>
      {differences.length === 0 ? (
        <p className="text-sm">{t(copy.no_differences)}</p>
      ) : (
        <div className="max-w-full overflow-x-auto">
          <Table aria-label={t(copy.title)}>
            <TableHeader>
              <TableRow>
                {[copy.col_field, copy.col_theirs, copy.col_yours].map((key) => (
                  <TableHead key={key}>{t(key)}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {differences.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="min-w-32 whitespace-normal">{d.label}</TableCell>
                  <TableCell className="min-w-40 max-w-xs whitespace-normal [overflow-wrap:anywhere]">
                    <bdi>{d.theirs}</bdi>
                  </TableCell>
                  <TableCell className="min-w-40 max-w-xs whitespace-normal [overflow-wrap:anywhere]">
                    <bdi>{d.mine}</bdi>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={onLoadTheirs}>
          {t(copy.load_theirs)}
        </Button>
        <Button variant="destructive" disabled={busy} onClick={onSaveMine}>
          {t(copy.save_mine)}
        </Button>
      </div>
    </section>
  );
}
